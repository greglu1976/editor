with open(r'g:\editor\ea_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '    def update_cabinets_and_kits(self):\n'

new = (
    '    def place_functional_block(self):\n'
    '        """Поставить выбранный функциональный блок на схему редактора."""\n'
    '        node = self._selected()\n'
    '        if not node or node[0] != "fb_entry" or not self._data:\n'
    '            return\n'
    '        entry = node[1]\n'
    '        place = getattr(self.app, "_place_functional_block", None)\n'
    '        if place is None:\n'
    '            # Запасной путь: поставить как шкаф, взяв блок из каталога\n'
    '            place = getattr(self.app, "_place_cabinet", None)\n'
    '        if place is None:\n'
    '            messagebox.showinfo(\n'
    '                "ФБ на схему",\n'
    '                "Окно открыто без редактора схем: размещать некуда.",\n'
    '                parent=self)\n'
    '            return\n'
    '        try:\n'
    '            place(entry)\n'
    '        except Exception as exc:                      # noqa: BLE001\n'
    '            messagebox.showerror("ФБ на схему",\n'
    '                                 "Не удалось разместить ФБ:\\n%s" % exc,\n'
    '                                 parent=self)\n'
    '            return\n'
    '        name = (entry.get("name") or entry.get("russian_path")\n'
    '                or entry.get("iec_name") or "")\n'
    '        self.status.config(text="ФБ \u00ab%s\u00bb размещён на схеме" % name)\n'
    '\n'
    '    def rebuild_functional_blocks(self):\n'
    '        """Пересобрать каталог ФБ из текущих шкафов и сохранить стандарт."""\n'
    '        if not self._data or not self._path:\n'
    '            messagebox.showinfo("Функциональные блоки",\n'
    '                                "Стандарт не выбран.", parent=self)\n'
    '            return\n'
    '        count = es.rebuild_functional_blocks(self._data)\n'
    '        try:\n'
    '            es.save(self._data, self._path)\n'
    '        except OSError as exc:\n'
    '            messagebox.showerror("Функциональные блоки",\n'
    '                                 "Не удалось сохранить:\\n%s" % exc,\n'
    '                                 parent=self)\n'
    '            return\n'
    '        self._fill_tree()\n'
    '        self.status.config(\n'
    '            text="\u041a\u0430\u0442\u0430\u043b\u043e\u0433 \u0424\u0411 \u043f\u0435\u0440\u0435\u0441\u043e\u0431\u0440\u0430\u043d: %d \u0437\u0430\u043f\u0438\u0441\u0435\u0439" % count)\n'
    '        messagebox.showinfo(\n'
    '            "\u0424\u0443\u043d\u043a\u0446\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u044b\u0435 \u0431\u043b\u043e\u043a\u0438",\n'
    '            "\u041a\u0430\u0442\u0430\u043b\u043e\u0433 \u043f\u0435\u0440\u0435\u0441\u043e\u0431\u0440\u0430\u043d: %d \u0437\u0430\u043f\u0438\u0441\u0435\u0439 (\u0421\u0442\u0430\u043d\u0434\u0430\u0440\u0442 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d)." % count,\n'
    '            parent=self)\n'
    '\n'
    '    def update_cabinets_and_kits(self):\n'
)

if old in content:
    content = content.replace(old, new, 1)
    with open(r'g:\editor\ea_ui.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('NOT FOUND')
