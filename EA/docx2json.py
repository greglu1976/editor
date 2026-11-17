#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перенос данных проекта СТО из docx в JSON по структуре модели EA (EA/structure.eapx).

Структура JSON повторяет классы модели:
  Standard -> Section -> Subsection -> Clause -> Subclause (+ Table/TableRow/Figure)
  Standard -> Cabinet -> Kit -> IED (+ Port/Component/PowerSupply/TerminalBlock)

Данные хранятся один раз — в Cabinet. Таблицы шкафов в дереве документа
(Section/Subsection) остаются только формой: номер, название, ссылка, шапка
(для «Описание ШЭТ» — ключи с пустыми значениями) и ссылка `cabinet` на шифр
шкафа, из которого берутся строки. Таблицы вне шкафов (термины, сокращения,
применимость) и таблицы неизвестного модели вида остаются с данными — им
неоткуда их подтягивать.

Разметка томов отличается: в томах 1 и 3 стили «ДОК Текст ур1/ур2/ур3»,
в томах 5 и 7 — «ДОК Текст 3/4уров» и «3уров». Поддерживаются оба набора.
Название и шифр берутся с титула и из имени файла, поэтому команда без
аргументов обрабатывает том 5, а для остальных достаточно пути к docx:

    python3 EA/docx2json.py [docx] [json]
"""

import json
import re
import sys
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

BASE = Path(__file__).resolve().parent
SRC = BASE / "Раздел 4.16_т. 5_СТО ШЭТ СКРМ II_Ред.2.docx"

# --- стили docx -----------------------------------------------------------------

# Тома 1 и 3 размечены стилями «ур1/ур2/ур3», тома 5 и 7 — «3/4уров»,
# поэтому каждый уровень — набор допустимых стилей.
S_SECTION = {"ДОК Текст 3/4уров 1-раздел", "ДОК Текст ур1 раздел"}
S_SUBSECTION = {"ДОК Текст 3уров 2-пункт", "ДОК Текст ур2 подраздел"}
S_CLAUSE = {"ДОК Текст 3уров 3-подпункт", "ДОК Текст ур3 пункт"}
S_APPX = {"ПРИЛ Заголовок", "ДОК ПРИЛ ур1 Заголовок"}
S_APPX_CLAUSE = {"ПРИЛ 2уров 1-пункт", "ДОК ПРИЛ ур2 раздел"}
S_TABLE_CAP = {"ДОК Таблица Название", "ПРИЛ Таблица Название",
               "ДОК ПРИЛ Таблица Название"}
S_FIG_CAP = {"ДОК Рисунок Название", "ПРИЛ Рисунок Название",
             "ДОК ПРИЛ Рисунок Название"}
S_HEADING = "ДОК Заголовок вкл в содержание"
SKIP_STYLES = {"ДОК титул", "toc 1", "toc 2",
               "ДОК Заголовок не вкл в содержание",
               "ДОК Заголовок не вкл в содержание по центру"}

#: Виды таблиц шкафа — те же, что в ``ea_standard.KINDS``. Таблицы другого
#: вида остаются таблицами документа со своими строками.
TABLE_KINDS = (
    ("описание шэт", "description"),
    ("входные аналоговые измерения", "analog_inputs"),
    ("внутренние дискретные цепи", "inner_discrete_circuits"),
    ("входящих сообщений", "incoming_goose_signals"),
    ("функциональные клавиши", "functional_buttons"),
    ("светодиодная сигнализация", "leds"),
    ("сообщения и отчеты", "datasets"),
    ("исходящих сообщений", "goose_signals"),
    ("исходящих отчетов", "report_signals"),
    ("осциллографируемые", "osc_analog_signals"),
    ("команды управления", "control_commands"),
    ("основные параметры функций", "functions"),
    ("ряды зажимов", "terminal_blocks"),
    ("основные компоненты", "components"),
)

DITTO = ("»", '"', "''")


def norm(text):
    return re.sub(r"[ \t\u00a0]+", " ", text.replace("\r", "")).strip()


def one_line(text):
    return re.sub(r"\s*\n\s*", " ", norm(text))


def dedup_cells(row):
    """Ячейки строки без повторов, вызванных объединением."""
    out = []
    for cell in row.cells:
        if not out or out[-1][0] is not cell._tc:
            out.append((cell._tc, norm(cell.text)))
    return [t for _, t in out]


def raw_cells(row):
    return [norm(c.text) for c in row.cells]


def is_note_row(cells):
    if not cells:
        return False
    first = cells[0]
    return first.lower().startswith("примечание") and all(c == first for c in cells)


def table_rows(table):
    rows = []
    grid = len(table.columns)
    for i, row in enumerate(table.rows):
        cells = raw_cells(row)
        rows.append({
            "content": cells,
            "is_header_first_row": i == 0,
            "is_header_second_row": i == 1 and len(dedup_cells(table.rows[0])) < grid,
        })
    return rows


# --- счётчики и дерево ----------------------------------------------------------

class DocBuilder:
    def __init__(self):
        self.standard = {
            "name": "",
            "code": "",
            "property": "",
            "date": "",
            "sections": [],
            "cabinets": [],
            "containers": [],
        }
        self.section = None
        self.subsection = None
        self.clause = None
        self.sec_no = 0
        self.sub_no = 0
        self.cl_no = 0
        self.tab_no = 0
        self.fig_no = 0
        self.letter = ""
        self.pending_caption = None
        self.pending_fig = None
        self.started = False
        self.sub_text = ""

    # -- контейнеры --------------------------------------------------------------

    def _flush_text(self):
        """Текст подраздела без класса Paragraph — в content раздела."""
        if not self.sub_text:
            return
        if self.section is not None:
            self.section["content"] = (self.section["content"] + "\n" + self.sub_text).strip("\n")
        self.sub_text = ""

    def add_section(self, number, header, style):
        self._flush_text()
        sec = {
            "number": number,
            "header": header,
            "header_style": style,
            "content": "",
            "subsections": [],
            "tables": [],
            "figures": [],
        }
        self.standard["sections"].append(sec)
        self.section, self.subsection, self.clause = sec, None, None
        self.sub_no = self.cl_no = self.tab_no = self.fig_no = 0
        return sec

    def add_subsection(self, header, style):
        self._flush_text()
        self.sub_no += 1
        self.cl_no = 0
        sub = {
            "number": f"{self.section['number']}.{self.sub_no}",
            "header": header,
            "header_style": style,
            "clauses": [],
            "tables": [],
            "figures": [],
        }
        self.section["subsections"].append(sub)
        self.subsection, self.clause = sub, None
        return sub

    def add_clause(self, text, style):
        self.cl_no += 1
        base = self.subsection["number"] if self.subsection else self.section["number"]
        if self.sub_text:
            text = (self.sub_text + "\n" + text).strip("\n")
            self.sub_text = ""
        cl = {
            "number": f"{base}.{self.cl_no}",
            "content": text,
            "subclauses": [],
            "tables": [],
            "figures": [],
        }
        if self.subsection:
            self.subsection["clauses"].append(cl)
        else:
            self.section.setdefault("clauses", []).append(cl)
        self.clause = cl
        return cl

    def add_paragraph(self, text):
        if not text:
            return
        if self.clause is not None:
            self.clause["content"] = (self.clause["content"] + "\n" + text).strip("\n")
        elif self.subsection is not None:
            self.sub_text = (self.sub_text + "\n" + text).strip("\n")
        elif self.section is not None:
            self.section["content"] = (self.section["content"] + "\n" + text).strip("\n")

    def container(self):
        return self.subsection or self.section

    def add_table(self, table):
        if not self.started or self.section is None:
            return
        cap = self.pending_caption or {"name": "", "style": ""}
        self.pending_caption = None
        number = ""
        if cap["name"]:
            self.tab_no += 1
            number = f"{self.section['number']}.{self.tab_no}" if self.section["number"] else ""
        node = {
            "number": number,
            "name": cap["name"],
            "reference": f"Таблица {number}" if number else "",
            "rows": table_rows(table),
            "_rows": [dedup_cells(r) for r in table.rows],
        }
        self.container()["tables"].append(node)

    def add_figure(self, name):
        self.fig_no += 1
        number = f"{self.section['number']}.{self.fig_no}" if self.section["number"] else ""
        node = {
            "number": number,
            "name": name,
            "reference": f"Рисунок {number}" if number else "",
        }
        self.container()["figures"].append(node)

    # -- разбор документа --------------------------------------------------------

    def feed_paragraph(self, p):
        style, text = p.style.name, norm(p.text)
        if style in SKIP_STYLES or not text:
            return
        if text.startswith("Рисунок") and re.search(r"-\s*Продолжение", text):
            return
        if not self.started:
            if style == S_HEADING and text == "Введение":
                self.started = True
            else:
                return
        if style in S_SECTION or style == S_HEADING or style in S_APPX:
            if style in S_APPX:
                self.letter = "АБВГД"[len([s for s in self.standard["sections"] if s["header_style"] in S_APPX])]
                header = one_line(re.sub(r"^\(.*?\)", "", text))
                self.add_section(self.letter, header, style)
            elif style == S_HEADING:
                self.letter = ""
                self.add_section("", text, style)
            else:
                self.letter = ""
                self.sec_no += 1
                self.add_section(str(self.sec_no), text, style)
        elif style in S_SUBSECTION:
            self.add_subsection(text, style)
        elif style in S_CLAUSE or style in S_APPX_CLAUSE:
            self.add_clause(text, style)
        elif style in S_TABLE_CAP:
            self.pending_caption = {"name": text, "style": style}
        elif style in S_FIG_CAP:
            if re.search(r"-\s*Продолжение", text):
                return
            self.add_figure(text)
        else:
            self.add_paragraph(text)

    def result(self):
        self._flush_text()
        return self.standard


# --- разбор данных шкафов -------------------------------------------------------

def clean(value):
    return one_line(value)


def join_lines(value):
    parts = [x.strip().strip(",") for x in value.split("\n")]
    return ", ".join(x for x in parts if x)


def split_ditto(value, prev):
    v = clean(value)
    return prev if v in DITTO else v


def split_signal_path(path):
    """CAPCBOFF1/RBRE1.BlkOp.stVal -> (DO, DA)."""
    p = clean(path)
    if not p:
        return "", ""
    if "." in p:
        do, da = p.rsplit(".", 1)
        return do, da
    return p, ""


def table_by_caption(sub, needle, ied_number=None):
    """Таблица по фрагменту названия; при ``ied_number`` — только своя ИЭУ.

    Таблицы «ИЭУ1, ИЭУ2» (общие) подходят обоим номерам.
    """
    for t in sub["tables"]:
        name = t["name"]
        if needle.lower() not in name.lower():
            continue
        if ied_number is not None:
            found = {int(x) for x in re.findall(r"ИЭУ\s*(\d+)", name, re.I)}
            if found and ied_number not in found:
                continue
        return t
    return None


def ied_numbers(sub):
    """Номера ИЭУ шкафа по названиям таблиц.

    Общая таблица «ИЭУ1 (ИЭУ2)» или «ИЭУ1, ИЭУ2» — одно ИЭУ: данные в ней
    общие. Раздельные таблицы «ИЭУ1» и «ИЭУ2» — два ИЭУ.
    """
    singles = set()
    for table in sub["tables"]:
        found = {int(x) for x in re.findall(r"ИЭУ\s*(\d+)", table["name"], re.I)}
        if len(found) == 1:
            singles |= found
    return sorted(singles) or [1]


def form_rows(table):
    """Форма таблицы шкафа для СТО: шапка без данных (строки берутся из Cabinet).

    У «Описание ШЭТ» шапки нет — форма это ключи первого столбца, значения
    подставляет шкаф. У остальных таблиц остаются строки шапки: одна, а у
    таблиц с двухъярусной шапкой («Ряды зажимов», «исходящих отчетов») — две.
    """
    name = table["name"].lower()
    if "описание шэт" in name:
        form = []
        for row in table["rows"]:
            cells = list(row["content"])
            form.append({
                "content": [cells[0]] + [""] * (len(cells) - 1) if cells else [],
                "is_header_first_row": row["is_header_first_row"],
                "is_header_second_row": row["is_header_second_row"],
            })
        return form
    height = 2 if ("ряды зажимов" in name or "исходящих отчетов" in name) else 1
    return table["rows"][:height]


def parse_description(table):
    """Таблица «Описание ШЭТ ...» (ключ-значение)."""
    data = {}
    for row in table["_rows"]:
        if len(row) < 2:
            continue
        key, value = row[0], row[1]
        if key and key not in data:
            data[key] = value
    return data


def find_value(desc, prefix):
    for k, v in desc.items():
        if k.lower().startswith(prefix.lower()):
            return v
    return ""


def parse_power_supplies(value):
    items = [clean(x.lstrip("-–").strip(" ;.")) for x in re.split(r"[;\n]", value)]
    return [{"purpose": i} for i in items if i]


def parse_analog_inputs(table):
    out = []
    for row in table["_rows"][1:]:
        c = row
        if len(c) < 4 or is_note_row(c):
            continue
        out.append({
            "circuit_type": c[0],
            "test_block": c[1],
            "contacts_count": c[2],
            "note": c[3],
        })
    return out


def parse_discrete_circuits(table):
    out = []
    for row in table["_rows"][1:]:
        c = row
        if len(c) < 3 or is_note_row(c):
            continue
        out.append({
            "discrete_signal": c[0],
            "direction": c[1],
            "note": c[2],
        })
    return out


def parse_incoming(table):
    out, prev_source, prev_model = [], "", ""
    for row in table["_rows"][1:]:
        c = row
        if len(c) < 5 or is_note_row(c):
            continue
        model = prev_model if clean(c[1]) in DITTO else join_lines(c[1])
        prev_model = model
        source = split_ditto(c[2], prev_source)
        prev_source = source
        out.append({
            "signal": c[0],
            "info_model": model,
            "source": source,
            "max_number": int(c[3]) if c[3].isdigit() else None,
            "source_number": None,
            "RAS": c[4],
            "note": "",
        })
    return out


def parse_function_buttons(table):
    out = []
    for row in table["_rows"][1:]:
        c = row
        if len(c) < 4 or is_note_row(c):
            continue
        out.append({
            "mapping": c[0],
            "short_name": c[1],
            "disable_condition": c[2],
            "enable_condition": c[3],
        })
    return out


def parse_leds(table):
    out = []
    for row in table["_rows"][1:]:
        c = row
        if len(c) < 3 or is_note_row(c):
            continue
        out.append({
            "mapping": c[0],
            "name": c[1],
            "mode": c[2],
            "note": "",
        })
    return out


def parse_messages(table):
    """Таблица «Сообщения и отчеты, исходящие от ИЭУ»."""
    messages, reports = [], []
    mode, prev_sender = None, ""
    for row in table["_rows"][1:]:
        if not row:
            continue
        purpose = row[0]
        if purpose.lower().startswith("сообщени"):
            mode = "msg"
            continue
        if purpose.lower().startswith("отчет"):
            mode = "rpt"
            continue
        if is_note_row(row) or len(row) < 6:
            continue
        sender, ident, ds, cls, note = row[1:6]
        sender = split_ditto(sender, prev_sender)
        prev_sender = sender
        item = {
            "purpose": purpose,
            "sender": sender,
            "id": ident,
            "dataset": ds,
            "class": cls,
            "note": note,
        }
        (messages if mode == "msg" else reports).append(item)
    return messages, reports


def parse_outgoing_goose(table):
    """Таблица «Информационные сигналы в составе исходящих сообщений»."""
    datasets, current, prev_dest = {}, None, ""
    for row in table["_rows"][1:]:
        c = row
        if len(c) < 3:
            continue
        if c[0].lower().startswith("имя набора данных"):
            current = c[1]
            datasets[current] = []
            prev_dest = ""
            continue
        if is_note_row(c) or current is None:
            continue
        destination = split_ditto(c[2], prev_dest)
        prev_dest = destination
        do, da = split_signal_path(c[1])
        datasets[current].append({
            "name": c[0],
            "info_model": clean(c[1]),
            "destination": destination,
            "note": "",
            "status": "",
            "KT": "",
            "cus": "",
            "rdu": "",
            "RAS": "",
            "DO": do,
            "DA": da,
        })
    return datasets


def parse_outgoing_reports(table):
    """Таблица «Информационные сигналы в составе исходящих отчетов»."""
    datasets, current = {}, None
    for row in table["_rows"]:
        c = row
        if not c:
            continue
        if c[0].lower().startswith("имя набора данных"):
            current = (c[1] if len(c) > 1 else "").replace(":", "").strip()
            datasets[current] = []
            continue
        if len(c) < 8:
            continue
        if is_note_row(c) or current is None:
            continue
        datasets[current].append({
            "name": c[0],
            "info_model": "",
            "destination": "",
            "note": "",
            "status": c[1],
            "KT": c[2],
            "cus": c[3],
            "rdu": c[4],
            "RAS": c[5],
            "DO": c[6],
            "DA": c[7],
        })
    return datasets


def parse_osc(table):
    out, prev = [], ""
    for row in table["_rows"][1:]:
        c = row
        if len(c) < 4 or is_note_row(c):
            continue
        desc = split_ditto(c[0], prev)
        prev = desc
        out.append({
            "description": desc,
            "canal": int(c[1]) if c[1].isdigit() else None,
            "name": c[2],
            "startRAS": c[3],
        })
    return out


def parse_commands(table):
    out = []
    for row in table["_rows"][1:]:
        c = row
        if len(c) < 2 or is_note_row(c):
            continue
        out.append({"name": c[0], "info_model": clean(c[1])})
    return out


def parse_functions(table, main_funcs, its_funcs):
    out, current = [], None
    for row in table["_rows"][1:]:
        c = row
        if not c or is_note_row(c):
            continue
        if len(c) < 3:
            # объединённая строка-заголовок функции
            name = c[0]
        else:
            name, explanation, states = c[0], c[1], c[2]
        if len(c) < 3 or (name and name == explanation == states):
            group, _, func = name.partition(" / ")
            current = {
                "name": clean(func or group),
                "russian_path": clean(group),
                "isMainFunction": clean(group) in main_funcs,
                "isInITS": clean(group) in its_funcs,
                "iec_name": "",
                "parameters": [],
            }
            out.append(current)
            continue
        if current is None:
            continue
        current["parameters"].append({
            "name": name,
            "description": explanation,
            "conditions": states,
        })
    return out


def parse_terminals(table):
    block = {"text": table["name"], "rows": []}
    for row in table["_rows"][2:]:
        c = row
        if len(c) < 5 or is_note_row(c):
            continue
        number, qty, ftype, ctype, purpose = c[:5]
        if not qty and not ftype and not ctype:
            if number not in ("-", ""):
                block["rows"].append({"location": number, "terminals": []})
            continue
        if not block["rows"]:
            block["rows"].append({"location": "", "terminals": []})
        block["rows"][-1]["terminals"].append({
            "number": number,
            "quantity": int(qty) if qty.isdigit() else None,
            "function_type": ftype,
            "connection_type": ctype,
            "purpose": purpose,
        })
    return block


def parse_components(table):
    out = []
    for row in table["_rows"][1:]:
        c = row
        if len(c) < 3 or is_note_row(c):
            continue
        out.append({
            "name": c[0],
            "description": c[1],
            "quantity": c[2],
        })
    return out


def build_ied(sub, desc, number, multi, main_funcs, its_funcs):
    """Данные одного ИЭУ из таблиц подраздела."""
    def pick(needle):
        return table_by_caption(sub, needle, number if multi else None)

    ied = {
        "number": number,
        "analog_inputs": [],
        "osc_analog_signals": [],
        "incoming_goose_signals": [],
        "inner_discrete_circuits": [],
        "datasets": [],
        "ports": [],
        "functional_buttons": [],
        "leds": [],
        "control_commands": [],
        "functions": [],
    }

    t = pick("Входные аналоговые измерения")
    if t:
        ied["analog_inputs"] = parse_analog_inputs(t)
    t = pick("Внутренние дискретные цепи")
    if t:
        ied["inner_discrete_circuits"] = parse_discrete_circuits(t)
    t = pick("входящих сообщений")
    if t:
        ied["incoming_goose_signals"] = parse_incoming(t)
    t = pick("Функциональные клавиши")
    if t:
        ied["functional_buttons"] = parse_function_buttons(t)
    t = pick("Светодиодная сигнализация")
    if t:
        ied["leds"] = parse_leds(t)
    t = pick("Осциллографируемые")
    if t:
        ied["osc_analog_signals"] = parse_osc(t)
    t = pick("Команды управления")
    if t:
        ied["control_commands"] = parse_commands(t)
    t = pick("Основные параметры функций")
    if t:
        ied["functions"] = parse_functions(t, main_funcs, its_funcs)

    # наборы данных: сообщения (GOOSE) и отчеты (MMS)
    msg_defs, rpt_defs = [], []
    t = pick("Сообщения и отчеты")
    if t:
        msg_defs, rpt_defs = parse_messages(t)

    goose = {}
    t = pick("исходящих сообщений")
    if t:
        goose = parse_outgoing_goose(t)
    reports = {}
    t = pick("исходящих отчетов")
    if t:
        reports = parse_outgoing_reports(t)

    used = set()
    for item in msg_defs:
        name = item["dataset"] or next((k for k in goose if k not in used), "")
        used.add(name)
        ied["datasets"].append({
            "name": name,
            "id": item["id"],
            "sender": item["sender"],
            "class": item["class"],
            "mapping": item["purpose"],
            "note": item["note"],
            "signals": goose.get(name, []),
        })
    for item in rpt_defs:
        name = item["dataset"] or next((k for k in reports if k not in used), "")
        used.add(name)
        ied["datasets"].append({
            "name": name,
            "id": item["id"],
            "sender": item["sender"],
            "class": item["class"],
            "mapping": item["purpose"],
            "note": item["note"],
            "signals": reports.get(name, []),
        })
    # наборы данных, для которых нет строки в таблице сообщений
    for name, signals in goose.items():
        if not any(d["name"] == name for d in ied["datasets"]):
            ied["datasets"].append({
                "name": name, "id": "", "sender": "", "class": "I",
                "mapping": "", "note": "", "signals": signals,
            })
    for name, signals in reports.items():
        if not any(d["name"] == name for d in ied["datasets"]):
            ied["datasets"].append({
                "name": name, "id": "", "sender": "", "class": "-",
                "mapping": "", "note": "", "signals": signals,
            })

    ied["ports"] = [
        {"description": clean(x.lstrip("-–").strip(" ;"))}
        for x in re.split(r"[;\n]", find_value(desc, "Цифровые порты"))
        if clean(x.strip(" -–;"))
    ]
    return ied


def build_cabinet(sub):
    desc_table = table_by_caption(sub, "Описание ШЭТ")
    if desc_table is None:
        return None
    desc = parse_description(desc_table)

    cypher = clean(find_value(desc, "Шифр шкафа"))
    main_funcs = {clean(x) for x in re.split(r",", find_value(desc, "Основные функции")) if clean(x)}
    its_funcs = {clean(x) for x in re.split(r",", find_value(desc, "Функции ИТС")) if clean(x)}

    components_table = table_by_caption(sub, "Основные компоненты")
    components = parse_components(components_table) if components_table else []

    numbers = ied_numbers(sub)
    multi = len(numbers) > 1
    ieds = [build_ied(sub, desc, n, multi, main_funcs, its_funcs)
            for n in numbers]

    cabinet = {
        "cypher": cypher,
        "architecture": clean(find_value(desc, "Архитектура")),
        "name": clean(find_value(desc, "Наименование шкафа")),
        "controllable_element": clean(find_value(desc, "Управляемый элемент")),
        "protected_element": clean(find_value(desc, "Защищаемый элемент")),
        "scope": clean(find_value(desc, "Область применения")),
        "description": sub["clauses"][0]["content"] if sub["clauses"] else "",
        "type": "ШЭТ",
        "tag": "",
        "group": "",
        "power_supplies": parse_power_supplies(find_value(desc, "Вводы питания")),
        "components": components,
        "terminal_blocks": [],
        "kits": [{
            "number": 1,
            "description": "Комплект ИЭУ шкафа",
            "type": "ИЭУ",
            "tag": "",
            "group": "",
            "ieds": ieds,
        }],
        "containers": [],
    }

    t = table_by_caption(sub, "Ряды зажимов")
    if t:
        cabinet["terminal_blocks"] = [parse_terminals(t)]

    return cabinet


def strip_service_keys(node):
    """Убирает служебные ключи (исходные строки таблиц) перед записью."""
    if isinstance(node, dict):
        node.pop("_rows", None)
        for value in node.values():
            strip_service_keys(value)
    elif isinstance(node, list):
        for value in node:
            strip_service_keys(value)


# --- main -----------------------------------------------------------------------

def table_kind(name):
    """Вид данных таблицы шкафа или None для таблицы документа."""
    low = (name or "").lower()
    for needle, kind in TABLE_KINDS:
        if needle in low:
            return kind
    return None


def document_meta(document, src):
    """Название СТО с титула и шифр по имени файла."""
    name = ""
    for p in document.paragraphs:
        text = one_line(p.text)
        found = re.search(r"Технический отчет, содержащий проект СТО «(.+?)»", text)
        if found and found.group(1) != "Типовые шкафы ШЭТ РЗА и отсеки ОЭТ (корректировка)":
            name = found.group(1)
    volume = ""
    found = re.search(r"_т\.\s*(\d+)_", src.name)
    if found:
        volume = found.group(1)
    code = f"СТО (проект) Раздел 4.16, т. {volume}, ред. 2" if volume else ""
    return name, code


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC

    document = docx.Document(str(src))
    builder = DocBuilder()

    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            builder.feed_paragraph(Paragraph(child, document))
        elif child.tag.endswith("}tbl"):
            builder.add_table(Table(child, document))

    data = builder.result()

    # титульные сведения
    data["name"], data["code"] = document_meta(document, src)
    data["property"] = "ПАО «Россети»"
    data["date"] = ""
    dst = (Path(sys.argv[2]) if len(sys.argv) > 2
           else src.with_name((data["code"] or src.stem) + ".json"))

    for section in data["sections"]:
        for sub in section["subsections"]:
            cabinet = build_cabinet(sub)
            if not cabinet:
                continue
            data["cabinets"].append(cabinet)
            for table in sub["tables"]:
                if table_kind(table["name"]) is None:
                    continue
                form = {key: table[key] for key in ("number", "name", "reference")}
                form["cabinet"] = cabinet["cypher"]
                form["rows"] = form_rows(table)
                table.clear()
                table.update(form)

    strip_service_keys(data)
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    tables = sum(len(s["tables"]) + sum(len(x["tables"]) for x in s["subsections"])
                 for s in data["sections"])
    print(f"секций: {len(data['sections'])}, таблиц: {tables}, шкафов: {len(data['cabinets'])}")
    for c in data["cabinets"]:
        ieds = c["kits"][0]["ieds"]
        print(f"  {c['cypher']}: ИЭУ {len(ieds)}, сигналов в наборах "
              f"{sum(len(d['signals']) for ied in ieds for d in ied['datasets'])}, "
              f"функций {sum(len(ied['functions']) for ied in ieds)}, клемм "
              f"{sum(len(r['terminals']) for b in c['terminal_blocks'] for r in b['rows'])}")
    print(f"записано: {dst}")


if __name__ == "__main__":
    main()
