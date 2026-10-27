# -*- coding: utf-8 -*-
"""Формирование отчётов в формате DOCX без внешних зависимостей.

Модуль сам собирает пакет OOXML (zip + word/document.xml + styles.xml),
поэтому работает на любой машине с Python — без python-docx и Word.

Использование:
    builder = DocxBuilder(landscape=False)
    builder.title("Отчёт по схеме")
    builder.subtitle("Сформирован: 26.10.2026 14:05")
    builder.heading("1. Сводка")
    builder.table(header=["Показатель", "Значение"],
                  rows=[["Шкафов РЗА", "12"]],
                  widths=[7000, 2638])
    builder.save("отчёт.docx")
"""

import os
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

#: Ширина полосы набора, twips (A4: 11906 × 16838, поля по 1134).
PORTRAIT_WIDTH = 9638
LANDSCAPE_WIDTH = 14570


def _run(text, bold=False, size=None, color=None, italic=False):
    """Элемент w:r с текстом."""
    props = []
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if color:
        props.append('<w:color w:val="{}"/>'.format(color))
    if size:
        props.append('<w:sz w:val="{}"/>'.format(int(size * 2)))
    rpr = "<w:rPr>{}</w:rPr>".format("".join(props)) if props else ""
    return ('<w:r>{}<w:t xml:space="preserve">{}</w:t></w:r>'
            .format(rpr, escape(str(text))))


def _paragraph(text, bold=False, size=None, align=None, space_after=0,
               space_before=0, color=None, italic=False):
    """Абзац w:p с одним текстовым фрагментом."""
    props = []
    if align:
        props.append('<w:jc w:val="{}"/>'.format(align))
    props.append('<w:spacing w:before="{}" w:after="{}"/>'
                 .format(int(space_before), int(space_after)))
    ppr = "<w:pPr>{}</w:pPr>".format("".join(props))
    return "<w:p>{}{}</w:p>".format(
        ppr, _run(text, bold=bold, size=size, color=color, italic=italic))


class DocxBuilder:
    """Сборка документа: заголовки, абзацы и таблицы с рамками."""

    def __init__(self, landscape=False):
        self.landscape = landscape
        self.text_width = LANDSCAPE_WIDTH if landscape else PORTRAIT_WIDTH
        self.body = []
        self.title_text = ""

    # ------------------------------------------------------------- текст
    def title(self, text):
        self.title_text = text
        self.body.append(_paragraph(text, bold=True, size=16, align="center",
                                    space_after=180))
        return self

    def subtitle(self, text):
        self.body.append(_paragraph(text, size=9, align="center",
                                    color="666666", space_after=60))
        return self

    def heading(self, text, level=1):
        size = 13 if level == 1 else 11
        self.body.append(_paragraph(text, bold=True, size=size,
                                    space_before=240, space_after=120))
        return self

    def paragraph(self, text, bold=False, size=10, align=None, color=None,
                  space_after=60):
        self.body.append(_paragraph(text, bold=bold, size=size, align=align,
                                    color=color, space_after=space_after))
        return self

    def page_break(self):
        self.body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        return self

    # ------------------------------------------------------------ таблица
    def table(self, header, rows, widths=None, font_size=9,
              aligns=None, header_fill="DCE6F1", empty_text="—"):
        """Таблица с рамками; первая строка — заголовок (повторяется)."""
        columns = len(header)
        if not widths:
            widths = [self.text_width // columns] * columns
        else:
            total = sum(widths)
            if total != self.text_width:
                widths = [int(width * self.text_width / total) for width in widths]
        aligns = aligns or ["left"] * columns

        parts = [
            '<w:tbl><w:tblPr>',
            '<w:tblStyle w:val="TableGrid"/>',
            '<w:tblW w:w="{}" w:type="dxa"/>'.format(self.text_width),
            '<w:tblLayout w:type="fixed"/>',
            '<w:tblCellMar>'
            '<w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/>'
            '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/>'
            '</w:tblCellMar>',
            '</w:tblPr><w:tblGrid>',
        ]
        parts.extend('<w:gridCol w:w="{}"/>'.format(width) for width in widths)
        parts.append('</w:tblGrid>')

        # заголовок
        parts.append('<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>')
        for index, cell in enumerate(header):
            parts.append(self._cell(cell, widths[index], font_size,
                                    align="center", bold=True,
                                    fill=header_fill))
        parts.append('</w:tr>')

        # данные
        for row in rows:
            parts.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>')
            for index in range(columns):
                value = row[index] if index < len(row) else ""
                if value is None or value == "":
                    value = empty_text
                parts.append(self._cell(value, widths[index], font_size,
                                        align=aligns[index]))
            parts.append('</w:tr>')

        parts.append('</w:tbl>')
        # небольшой отступ после таблицы
        self.body.append("".join(parts))
        self.body.append(_paragraph("", size=6, space_after=60))
        return self

    @staticmethod
    def _cell(text, width, font_size, align="left", bold=False, fill=None):
        shading = ('<w:shd w:val="clear" w:color="auto" w:fill="{}"/>'
                   .format(fill)) if fill else ""
        return (
            '<w:tc><w:tcPr><w:tcW w:w="{}" w:type="dxa"/>{}'
            '<w:vAlign w:val="center"/></w:tcPr>'
            '<w:p><w:pPr><w:spacing w:before="0" w:after="0"/>'
            '<w:jc w:val="{}"/></w:pPr>{}</w:p></w:tc>'
            .format(width, shading, align,
                    _run(text, bold=bold, size=font_size))
        )

    # --------------------------------------------------------------- файл
    def document_xml(self):
        section = (
            '<w:sectPr>'
            '<w:pgSz w:w="{}" w:h="{}"{} />'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
            'w:left="1134" w:header="708" w:footer="708" w:gutter="0"/>'
            '</w:sectPr>'
        ).format(16838 if self.landscape else 11906,
                 11906 if self.landscape else 16838,
                 ' w:orient="landscape"' if self.landscape else "")
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="{}" xmlns:r="{}"><w:body>{}{}</w:body>'
            '</w:document>'
            .format(W_NS, R_NS, "".join(self.body), section)
        )

    @staticmethod
    def styles_xml():
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="{}">'
            '<w:docDefaults><w:rPrDefault><w:rPr>'
            '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
            'w:cs="Times New Roman"/>'
            '<w:sz w:val="24"/><w:szCs w:val="24"/>'
            '<w:lang w:val="ru-RU"/>'
            '</w:rPr></w:rPrDefault>'
            '<w:pPrDefault><w:pPr><w:spacing w:after="60" w:line="264" '
            'w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
            '<w:name w:val="Normal"/><w:qFormat/></w:style>'
            '<w:style w:type="table" w:styleId="TableGrid">'
            '<w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/>'
            '<w:tblPr><w:tblBorders>'
            '<w:top w:val="single" w:sz="6" w:space="0" w:color="7F7F7F"/>'
            '<w:left w:val="single" w:sz="6" w:space="0" w:color="7F7F7F"/>'
            '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="7F7F7F"/>'
            '<w:right w:val="single" w:sz="6" w:space="0" w:color="7F7F7F"/>'
            '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
            '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
            '</w:tblBorders></w:tblPr></w:style>'
            '<w:style w:type="table" w:default="1" w:styleId="TableNormal">'
            '<w:name w:val="Normal Table"/><w:tblPr><w:tblCellMar>'
            '<w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/>'
            '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/>'
            '</w:tblCellMar></w:tblPr></w:style>'
            '</w:styles>'
            .format(W_NS)
        )

    def _core_xml(self):
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
            'metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:title>{title}</dc:title>'
            '<dc:creator>Редактор схем</dc:creator>'
            '<cp:lastModifiedBy>Редактор схем</cp:lastModifiedBy>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            '<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
            '</cp:coreProperties>'
            .format(title=escape(self.title_text or "Отчёт"),
                    now=now)
        )

    @staticmethod
    def _app_xml():
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/'
            'officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/'
            'officeDocument/2006/docPropsVTypes">'
            '<Application>Редактор схем</Application>'
            '</Properties>'
        )

    @staticmethod
    def _content_types_xml():
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types">'
            '<Default Extension="rels" ContentType="application/'
            'vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.'
            'main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/'
            'vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '</Types>'
        )

    def save(self, path):
        """Записывает .docx по указанному пути."""
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="{}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
            'package/2006/relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/extended-properties" '
            'Target="docProps/app.xml"/>'
            '</Relationships>'
        ).format(REL_NS)
        document_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="{}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'
        ).format(REL_NS)

        target_dir = os.path.dirname(os.path.abspath(path))
        if target_dir and not os.path.isdir(target_dir):
            os.makedirs(target_dir)

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._content_types_xml())
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr("word/document.xml", self.document_xml())
            archive.writestr("word/styles.xml", self.styles_xml())
            archive.writestr("word/_rels/document.xml.rels", document_rels)
            archive.writestr("docProps/core.xml", self._core_xml())
            archive.writestr("docProps/app.xml", self._app_xml())
        return path


def build_scheme_report(path, report):
    """Строит отчёт по схеме из подготовленных данных.

    report = {
        "title": "Отчёт по схеме",
        "subtitle": ["Сформирован: …", "…"],
        "sections": [
            {"title": "1. Сводка", "header": [...], "rows": [[...]],
             "widths": [...], "aligns": [...], "note": "…"},
        ],
    }
    """
    builder = DocxBuilder(landscape=report.get("landscape", False))
    builder.title(report.get("title", "Отчёт по схеме"))
    for line in report.get("subtitle") or []:
        builder.subtitle(line)
    for section in report.get("sections") or []:
        builder.heading(section.get("title", ""))
        if section.get("note"):
            builder.paragraph(section["note"], size=9, color="666666")
        rows = section.get("rows") or []
        if rows:
            builder.table(header=section.get("header") or ["Значение"],
                          rows=rows,
                          widths=section.get("widths"),
                          aligns=section.get("aligns"),
                          font_size=section.get("font_size", 9))
        else:
            builder.paragraph("Нет данных.", size=10, color="808080")
    for line in report.get("footer") or []:
        builder.paragraph(line, size=8, color="808080", space_after=40)
    return builder.save(path)


def build_selection_report(path, report):
    """Отчёт по выделенному элементу (шкаф или контейнер).

    report = {
        "title": "Отчёт по шкафу EL1",
        "subtitle": ["Сформирован: …"],
        "sections": [
            # пары «показатель — значение»
            {"title": "1. Общие сведения",
             "rows": [["Обозначение", "EL1"], ...]},

            # таблица с произвольными колонками
            {"title": "2. Шкафы в контейнере",
             "header": ["Слот", "Шкаф", ...],
             "rows": [[...]],
             "widths": [...], "aligns": [...]},

            # блоки: каждый — заголовок и свои пары
            {"title": "3. Комплекты",
             "blocks": [
                 {"head": "Комплект 1 — Типовой · используется",
                  "note": "…",
                  "rows": [["Функции", "ДЗТ, ГЗ Т"], ...]},
             ]},
        ],
        "footer": ["…"],
    }
    """
    builder = DocxBuilder(landscape=report.get("landscape", False))
    builder.title(report.get("title", "Отчёт"))
    for line in report.get("subtitle") or []:
        builder.subtitle(line)

    for section in report.get("sections") or []:
        builder.heading(section.get("title", ""))
        if section.get("note"):
            builder.paragraph(section["note"], size=9, color="666666")

        rows = section.get("rows") or []
        blocks = section.get("blocks") or []
        header = section.get("header")

        if header:
            builder.table(header=header, rows=rows,
                          widths=section.get("widths"),
                          aligns=section.get("aligns"),
                          font_size=section.get("font_size", 9))
        elif rows:
            builder.table(header=section.get("header") or ["Показатель",
                                                           "Значение"],
                          rows=rows,
                          widths=section.get("widths") or [3200, 6438],
                          aligns=section.get("aligns") or ["left", "left"],
                          font_size=section.get("font_size", 9))

        for block in blocks:
            head = block.get("head")
            if head:
                builder.paragraph(head, bold=True, size=10, space_after=40)
            if block.get("note"):
                builder.paragraph(block["note"], size=8, color="666666")
            block_rows = block.get("rows") or []
            if block_rows:
                builder.table(header=["Параметр", "Значение"],
                              rows=block_rows, widths=[3200, 6438],
                              aligns=["left", "left"], font_size=9)

        if not (header or rows or blocks):
            builder.paragraph("Нет данных.", size=10, color="808080")

    for line in report.get("footer") or []:
        builder.paragraph(line, size=8, color="808080", space_after=40)
    return builder.save(path)
