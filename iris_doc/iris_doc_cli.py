from importlib.metadata import files
import os
import sys
import argparse
from typing import Any, Dict, List

from xmlrpc.client import Boolean

from iris_doc.c_sharp.api_tagger_c_sharp import CSharpTagBuilder
from iris_doc.c_sharp.export_file_parser_c_sharp import ExportFileParserCSharp
from iris_doc.c_sharp.post_phase_c_sharp import PostPhaseCSharp
from iris_doc.configuration_reader import ConfigurationReader
from iris_doc.api_tagger import ApiTagger, TagBuilder
from iris_doc.dart.export_file_parser_dart import ExportFileParserDart
from iris_doc.dart.api_tagger_dart import DartTagBuilder
from iris_doc.dart.post_phase_dart import PostPhaseDart
from iris_doc.oc.export_file_parser_oc import ExportFileParserObjC
from iris_doc.oc.api_tagger_oc import ObjCTagBuilder
from iris_doc.oc.post_phase_oc import PostPhaseObjC
from iris_doc.export_file_parser import DefaultExportFileParser, ExportFileParser
from iris_doc.language_specification import CommentSource, LanguageFormat, LanguageSpecificationModule, LanguageSpecificationConfig

from iris_doc.post_phase import DefaultPostPhase, PostPhase
from iris_doc.tag2doc import Tag2Doc

import fs.osfs
from fs.base import FS
from fs.copy import copy_file
from iris_doc.ts.api_tagger_ts import TSTagBuilder

from iris_doc.ts.export_file_parser_ts import ExportFileParserTS

from fs.permissions import Permissions

import requests

from iris_doc.ts.post_phase_ts import PostPhaseTS


class TagToNoDocPostPhase(PostPhase):

    __format: LanguageFormat
    __code: str
    __tag2Doc: Tag2Doc

    def __init__(self, tag2Doc: Tag2Doc, format: LanguageFormat, code: str) -> None:
        self.__tag2Doc = tag2Doc
        self.__format = format
        self.__code = code

    def run(self) -> Any:
        codeLines: List[str] = self.__code.splitlines()
        newCodeLines: List[str] = []
        for line in codeLines:
            if line.strip().startswith("/*") and line.strip().endswith("*/"):
                newCodeLines.append(
                    self.__tag2Doc._generateComment(self.__format, None))
                continue

            newCodeLines.append(line)

        return '\n'.join(newCodeLines)


def _processExportFile(
        languageSpecificationConfig: LanguageSpecificationConfig,
        configPath: str,
        tagBuilder: TagBuilder,
        exportFileParser: ExportFileParser,
        postPhase: PostPhase,
        exportFilePath: str,
        templateFilePathList: List[str],
        fileSystem: FS,
        isForceMarkNoDoc: bool):
    config = ConfigurationReader(fileSystem)
    config.set_config(configPath)
    format = config.get_fmt()[1]

    module = LanguageSpecificationModule(
        fileSystem=fileSystem, config=languageSpecificationConfig)
    module.setLanguageSpecificationConfig(languageSpecificationConfig)
    for p in templateFilePathList:
        module.addTemplateFilePath(p)
    module.deserialize()

    exportFiles = exportFileParser.parseExportFiles(exportFilePath)
    for path in exportFiles:
        backupFilePath = path + ".backup"
        copy_file(fileSystem, path, fileSystem, backupFilePath)

        ApiTagger(fileSystem, tagBuilder).process(backupFilePath)

        code = fileSystem.readtext(backupFilePath)
        tag2Doc = Tag2Doc(
            format=format, commentSources=module.getAllCommentSources())
        processedCode = tag2Doc.process(code)

        if isForceMarkNoDoc:
            noDocPostPhase = TagToNoDocPostPhase(
                tag2Doc=tag2Doc, format=format, code=processedCode)
            processedCode = noDocPostPhase.run()

        backupFile = fileSystem.open(backupFilePath, mode="w")
        backupFile.write(processedCode)
        backupFile.flush()
        backupFile.close()

        copy_file(fileSystem, backupFilePath, fileSystem, path)

        fileSystem.remove(backupFilePath)

    postPhase.run()


def run():
    fileSystem = fs.osfs.OSFS("/")
    root = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(os.path.dirname(root)))

    parser = argparse.ArgumentParser(description='Iris doc generator')
    parser.add_argument('--config', '-c', type=str,
                        help='The path of the `fmt.json` file')
    parser.add_argument('--template', '-t', type=str,
                        help='The path of the doc json file')
    parser.add_argument('--template-url', type=str, action='append',
                        help='The github release url of the template file, which allow set multiple times, the json will be merge in file order')
    parser.add_argument('--language', choices=['dart', 'ts', 'c_sharp', 'oc'])
    parser.add_argument('--debug-show-tag', default=False, action='store_true',
                        help='Whether change the dita id type from callback to api')
    parser.add_argument('--export-file-path', type=str,
                        help='The path of the export file')
    args = parser.parse_args()

    isCallback2class: Boolean
    isCallback2api: Boolean
    idPatternV2 = True
    exportFilePath = args.export_file_path
    exportFilePath = os.path.realpath(exportFilePath)
    isForceMarkNoDoc = not args.debug_show_tag
    templateFile = args.template
    templateUrls = args.template_url
    configPath = args.config

    tagBuilder: TagBuilder
    exportFileParser: ExportFileParser
    postPhase: PostPhase

    buildDirPath = os.path.join(os.path.dirname(
        os.path.abspath(__file__)), 'build')
    if os.path.exists(buildDirPath):
        fileSystem.removetree(buildDirPath)

    fileSystem.makedirs(buildDirPath, Permissions(
        user='rwx', group='rwx', other='rwx'))

    lang = args.language
    if lang == "dart":
        isCallback2class = True
        isCallback2api = False
        exportFileParser = ExportFileParserDart(fileSystem=fileSystem)
        tagBuilder = DartTagBuilder()
        exportFileDir = os.path.dirname(exportFilePath)
        postPhase = PostPhaseDart(exportFileDir)
    elif lang == "oc":
        isCallback2class = False
        isCallback2api = True
        exportFileParser = ExportFileParserObjC(fileSystem=fileSystem)
        tagBuilder = ObjCTagBuilder()
        exportFileDir = os.path.dirname(exportFilePath)
        postPhase = PostPhaseObjC(exportFileDir)
    elif lang == "ts":
        isCallback2class = False
        isCallback2api = True
        exportFileParser = ExportFileParserTS(fileSystem=fileSystem)
        tagBuilder = TSTagBuilder()
        exportFileDir = os.path.dirname(exportFilePath)
        postPhase = PostPhaseTS(exportFileDir)
    elif lang == "c_sharp":
        isCallback2class = False
        isCallback2api = True
        exportFileParser = ExportFileParserCSharp(fileSystem=fileSystem)
        tagBuilder = CSharpTagBuilder()
        exportFileDir = os.path.dirname(exportFilePath)
        postPhase = PostPhaseCSharp(exportFileDir)
    else:
        isCallback2class = False
        isCallback2api = False
        exportFileParser = DefaultExportFileParser()
        tagBuilder = TagBuilder()
        postPhase = DefaultPostPhase()

    languageSpecificationConfig: LanguageSpecificationConfig = LanguageSpecificationConfig(
        isCallback2class=isCallback2class,
        isCallback2api=isCallback2api,
        idPatternV2=idPatternV2)


    templateFilePathList: List[str] = []

    if templateFile is None and templateUrls is not None:
        for templateUrl in templateUrls:
            data = requests.get(templateUrl)

            templateFileName = os.path.basename(os.path.normpath(templateUrl))

            # Save file data to local copy
            with fileSystem.open(os.path.join(buildDirPath, templateFileName), 'wb') as file:
                file.write(data.content)
                templateFilePathList.append(os.path.join(buildDirPath, templateFileName))
    else:
        templateFilePathList.append(templateFile)

    _processExportFile(languageSpecificationConfig=languageSpecificationConfig,
                       configPath=configPath,
                       tagBuilder=tagBuilder,
                       exportFileParser=exportFileParser,
                       postPhase=postPhase,
                       exportFilePath=exportFilePath,
                       templateFilePathList=templateFilePathList,
                       fileSystem=fileSystem,
                       isForceMarkNoDoc=isForceMarkNoDoc)

    fileSystem.close()
