import os
import sys
import argparse
from typing import Any, Dict, List
from xmlrpc.client import Boolean
from iris_doc.ConfigurationReadVerificationModule import ConfigurationReadVerificationModule
from iris_doc.api_tagger import ApiTagger, TagBuilder
from iris_doc.dart.export_file_parser_dart import ExportFileParserDart
from iris_doc.dart.api_tagger_dart import DartTagBuilder
from iris_doc.dart.post_phase_dart import PostPhaseDart
from iris_doc.export_file_parser import DefaultExportFileParser, ExportFileParser
from iris_doc.language_specification import CommentSource, LanguageFormat, LanguageSpecificationModule, LanguageSpecificationConfig

from iris_doc.post_phase import DefaultPostPhase, PostPhase
from iris_doc.tag2doc import Tag2Doc

import fs.osfs
from fs.base import FS
from fs.copy import copy_file
from iris_doc.ts.api_tagger_ts import TSTagBuilder

from iris_doc.ts.export_file_parser_ts import ExportFileParserTS


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


def __processExportFile(
        tagBuilder: TagBuilder,
        exportFileParser: ExportFileParser,
        postPhase: PostPhase,
        exportFilePath: str,
        fileSystem: FS,
        format: LanguageFormat,
        commentSources: Dict[str, CommentSource],
        isForceMarkNoDoc: bool):
    exportFiles = exportFileParser.parseExportFiles(exportFilePath)
    for path in exportFiles:
        backupFilePath = path + ".backup"
        copy_file(fileSystem, path, fileSystem, backupFilePath)

        ApiTagger(fileSystem, tagBuilder).process(backupFilePath)

        code = fileSystem.readtext(backupFilePath)
        tag2Doc = Tag2Doc(
            format=format, commentSources=commentSources)
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
    parser.add_argument('--language', choices=['dart', 'ts', 'c#'])
    parser.add_argument('--debug-show-tag', default=False, action='store_true',
                        help='Whether change the dita id type from callback to api')
    parser.add_argument('--export-file-path', type=str,
                        help='The path of the export file')
    args = parser.parse_args()

    isCallback2class: Boolean
    isCallback2api: Boolean
    idPatternV2 = True
    exportFilePath = args.export_file_path
    isForceMarkNoDoc = not args.debug_show_tag

    tagBuilder: TagBuilder
    exportFileParser: ExportFileParser
    postPhase: PostPhase

    lang = args.language
    if lang == "dart":
        isCallback2class = True
        isCallback2api = False
        exportFileParser = ExportFileParserDart(fileSystem=fileSystem)
        tagBuilder = DartTagBuilder()
        exportFileDir = os.path.dirname(exportFilePath)
        postPhase = PostPhaseDart(exportFileDir)
    elif lang == "ts":
        isCallback2class = False
        isCallback2api = True
        exportFileParser = ExportFileParserTS(fileSystem=fileSystem)
        tagBuilder = TSTagBuilder()
        postPhase = DefaultPostPhase()
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

    config = ConfigurationReadVerificationModule(fileSystem)
    config.set_config(args.config)
    format = config.get_fmt()[1]

    module = LanguageSpecificationModule(
        fileSystem=fileSystem, config=languageSpecificationConfig)
    module.setLanguageSpecificationConfig(languageSpecificationConfig)
    module.read_template_file(args.template)
    module.deserialize()

    __processExportFile(tagBuilder=tagBuilder,
                        exportFileParser=exportFileParser,
                        postPhase=postPhase,
                        exportFilePath=exportFilePath,
                        fileSystem=fileSystem,
                        format=format,
                        commentSources=module.getAllCommentSources(),
                        isForceMarkNoDoc=isForceMarkNoDoc)

    fileSystem.close()