# -*- coding: utf-8 -*-
"""Условные обозначения принципиальной схемы шкафа.

Сгенерировано из mount_elements/Чертеж1.txt и
mount_elements/test_block.txt скриптом tools/dxf_to_schematic.py.
Не редактируйте вручную — измените описание символов в скрипте
и запустите его заново.
"""

SCALE = 3

SYMBOLS = {
    'sc_current_input': {
        'title': 'Токовый вход',
        'prefix': 'TA',
        'source': 'токовый вход',
        'bbox': (-40.5, -9, 40.5, 9),
        'primitives': [
            ('line', -4.5, 0, 4.5, 0),
            ('poly', [(-40.5, -9), (-4.5, -9), (-4.5, 9), (-40.5, 9)], True),
            ('arc', 16.5, 0, 6, -180, 0),
            ('arc', 28.5, 0, 6, -180, 0),
            ('line', 34.5, 0, 40.5, 0),
            ('line', 4.5, 0, 10.5, 0),
        ],
        'ports': {
            'left': {'x': -40.5, 'y': 0, 'direction': 'in'},
            'right': {'x': 40.5, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_voltage_input': {
        'title': 'Вход напряжения',
        'prefix': 'TV',
        'source': 'вход напряжения',
        'bbox': (-40.5, -9, 40.5, 9),
        'primitives': [
            ('line', -4.5, 0, 4.5, 0),
            ('poly', [(-40.5, -9), (-4.5, -9), (-4.5, 9), (-40.5, 9)], True),
            ('arc', 10.5, 0, 6, -180, 0),
            ('arc', 34.5, 0, 6, -180, 0),
            ('arc', 22.5, 0, 6, -180, 0),
        ],
        'ports': {
            'left': {'x': -40.5, 'y': 0, 'direction': 'in'},
            'right': {'x': 40.5, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_break_point': {
        'title': 'Точка разрыва',
        'prefix': 'X',
        'source': 'Точка разрыва',
        'bbox': (-7.5, 0, 7.5, 0),
        'primitives': [
            ('line', 4.5, 0, -7.5, 0),
            ('poly', [(-1.5, 0), (7.5, 0)], False),
        ],
        'ports': {
            'left': {'x': -7.5, 'y': 0, 'direction': 'in'},
            'right': {'x': 7.5, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_lamp': {
        'title': 'Лампа',
        'prefix': 'HL',
        'source': 'лампа',
        'bbox': (-27, -12, 27, 12),
        'primitives': [
            ('line', -27, 0, -12, 0),
            ('line', 12, 0, 27, 0),
            ('circle', 0, 0, 12),
            ('line', -8.485, -8.485, 8.485, 8.485),
            ('line', -8.485, 8.485, 8.485, -8.485),
        ],
        'ports': {
            'left': {'x': -27, 'y': 0, 'direction': 'in'},
            'right': {'x': 27, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_busbar': {
        'title': 'Шинка',
        'prefix': 'BB',
        'source': 'Шинка',
        'bbox': (-18, -3, 18, 3),
        'primitives': [
            ('line', -18, -3, 18, -3),
            ('line', -18, 3, -18, -3),
            ('line', 18, 3, 18, -3),
            ('line', -18, 3, 18, 3),
        ],
        'ports': {
            'left': {'x': -18, 'y': 0, 'direction': 'in'},
            'right': {'x': 18, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_resistor': {
        'title': 'Резистор',
        'prefix': 'R',
        'source': 'Резистор',
        'bbox': (-27, -6, 27, 6),
        'primitives': [
            ('line', -27, 0, -15, 0),
            ('line', 15, 0, 27, 0),
            ('poly', [(-15, -6), (15, -6), (15, 6), (-15, 6)], True),
        ],
        'ports': {
            'left': {'x': -27, 'y': 0, 'direction': 'in'},
            'right': {'x': 27, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_device_terminal': {
        'title': 'Клемма устройства',
        'prefix': 'X',
        'source': 'Клемма устройства',
        'bbox': (-18, -9, 18, 9),
        'primitives': [
            ('poly', [(-18, -9), (18, -9), (18, 9), (-18, 9)], True),
        ],
        'ports': {
            'left': {'x': -18, 'y': 0, 'direction': 'in'},
            'right': {'x': 18, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_closing_contact': {
        'title': 'Замыкающий контакт',
        'prefix': 'KA',
        'source': 'замыкающий контакт',
        'bbox': (-40.5, -9.643, 40.5, 9.643),
        'primitives': [
            ('line', -4.5, 0.643, 4.5, 0.643),
            ('poly', [(-40.5, -8.357), (-4.5, -8.357), (-4.5, 9.643), (-40.5, 9.643)], True),
            ('line', 22.5, 0.643, 40.5, -9.643),
            ('line', 22.5, 0.643, 31.5, 0.643),
        ],
        'ports': {
            'left': {'x': -40.5, 'y': 0.643, 'direction': 'in'},
            'right': {'x': 40.5, 'y': -9.557, 'direction': 'out'},
        },
    },
    'sc_opening_contact': {
        'title': 'Размыкающий контакт',
        'prefix': 'KA',
        'source': 'размыкающий контакт',
        'bbox': (-42, -11.25, 42, 11.25),
        'primitives': [
            ('line', -6, -2.25, 3, -2.25),
            ('poly', [(-42, -11.25), (-6, -11.25), (-6, 6.75), (-42, 6.75)], True),
            ('line', 21, -2.25, 30, -2.25),
            ('line', 39, -2.25, 39, 11.25),
            ('line', 21, -2.25, 42, 9.75),
        ],
        'ports': {
            'left': {'x': -42, 'y': -2.25, 'direction': 'in'},
            'right': {'x': 42, 'y': 9.75, 'direction': 'out'},
        },
    },
    'sc_changeover_contact': {
        'title': 'Переключающий контакт',
        'prefix': 'SA',
        'source': 'переключающий контакт',
        'bbox': (-42, -13.5, 42, 13.5),
        'primitives': [
            ('line', -6, 4.5, 3, 4.5),
            ('poly', [(-42, -4.5), (-6, -4.5), (-6, 13.5), (-42, 13.5)], True),
            ('line', 21, 4.5, 30, 4.5),
            ('line', 39, -13.5, 39, -3),
            ('line', 21, 4.5, 42, -7.5),
            ('line', 3, -13.5, 3, -10.5),
        ],
        'ports': {
            'common': {'x': -42, 'y': 4.5, 'direction': 'in'},
            'contact1': {'x': 42, 'y': -7.5, 'direction': 'out'},
            'contact2': {'x': 3, 'y': -13.5, 'direction': 'out'},
        },
    },
    'sc_switch_on': {
        'title': 'Переключатель 2-позиционный (вкл.)',
        'prefix': 'SA',
        'source': 'Переключатель 2-позиционный, включенный',
        'bbox': (-27, -12, 27, 12),
        'primitives': [
            ('circle', -6, 0, 3),
            ('line', -27, 0, -18, 0),
            ('line', 18, 0, 27, 0),
            ('line', -18, -12, -18, 12),
            ('line', -6, -12, -6, 12),
            ('line', 6, -12, 6, 12),
            ('line', 18, -12, 18, 12),
        ],
        'ports': {
            'left': {'x': -27, 'y': 0, 'direction': 'in'},
            'right': {'x': 27, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_switch_off': {
        'title': 'Переключатель 2-позиционный (откл.)',
        'prefix': 'SA',
        'source': 'Переключатель 2-позиционный, отключенный',
        'bbox': (-27, -12, 27, 12),
        'primitives': [
            ('circle', 6, 0, 3),
            ('line', -27, 0, -18, 0),
            ('line', 18, 0, 27, 0),
            ('line', -18, -12, -18, 12),
            ('line', -6, -12, -6, 12),
            ('line', 6, -12, 6, 12),
            ('line', 18, -12, 18, 12),
        ],
        'ports': {
            'left': {'x': -27, 'y': 0, 'direction': 'in'},
            'right': {'x': 27, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_relay_coil': {
        'title': 'Катушка реле',
        'prefix': 'KA',
        'source': 'Катушка реле',
        'bbox': (-27, -10.5, 27, 10.5),
        'primitives': [
            ('line', -27, 10.5, -9, 10.5),
            ('line', 9, 10.5, 27, 10.5),
            ('line', -9, 10.5, 9, 0.214),
            ('line', -6, -10.5, 0, -10.5),
            ('line', 0, -10.5, 0, -7.5),
            ('line', 0, -4.5, 0, -1.5),
            ('line', 0, 1.5, 0, 5.357),
            ('line', 6, -10.5, 6, -7.5),
            ('line', 0, -10.5, 6, -10.5),
            ('line', -6, -10.5, -6, -7.5),
        ],
        'ports': {
            'left': {'x': -27, 'y': 10.5, 'direction': 'in'},
            'right': {'x': 27, 'y': 10.5, 'direction': 'out'},
        },
    },
    'sc_device': {
        'title': 'Устройство',
        'prefix': 'A',
        'source': 'устройство',
        'bbox': (-36, -36, 36, 36),
        'primitives': [
            ('line', -36, -36, 36, -36),
            ('line', 36, 36, 36, -36),
            ('line', -36, 36, -36, -36),
            ('line', -36, 36, 36, 36),
        ],
        'ports': {
            'left': {'x': -36, 'y': 0, 'direction': 'in'},
            'right': {'x': 36, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_discrete_input': {
        'title': 'Дискретный вход',
        'prefix': 'DI',
        'source': 'дискретный вход',
        'bbox': (-31.5, -9, 31.5, 9),
        'primitives': [
            ('line', 4.5, 0, 13.5, 0),
            ('poly', [(-31.5, -9), (4.5, -9), (4.5, 9), (-31.5, 9)], True),
            ('poly', [(13.5, -9), (31.5, -9), (31.5, 9), (13.5, 9)], True),
            ('line', 31.5, -9, 13.5, 9),
        ],
        'ports': {
            'left': {'x': -31.5, 'y': 0, 'direction': 'in'},
            'right': {'x': 31.5, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_feed_terminal': {
        'title': 'Клемма проходная',
        'prefix': 'X',
        'source': 'клемма проходная',
        'bbox': (-3, -3, 3, 3),
        'primitives': [
            ('circle', 0, 0, 3),
        ],
        'ports': {
            'left': {'x': -3, 'y': 0, 'direction': 'in'},
            'right': {'x': 3, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_disconnect_terminal': {
        'title': 'Клемма с размыкателем',
        'prefix': 'X',
        'source': 'клемма с размыкателем',
        'bbox': (-3, -3, 3, 3),
        'primitives': [
            ('circle', 0, 0, 3),
            ('line', 3, -3, -3, 3),
        ],
        'ports': {
            'left': {'x': -3, 'y': 0, 'direction': 'in'},
            'right': {'x': 3, 'y': 0, 'direction': 'out'},
        },
    },
    'sc_test_block': {
        'title': 'Тестовый блок',
        'prefix': 'TB',
        'source': 'Тестовый блок',
        'bbox': (-37.418, -23.088, 27, 8.912),
        'primitives': [
            ('line', -27, 0, -15, 0),
            ('line', -9, 0, 9, 0),
            ('line', -3, -6, -9, 0),
            ('line', -9, 0, -3, 6),
            ('line', -9, -6, -15, 0),
            ('line', -15, 0, -9, 6),
            ('line', 27, 0, 15, 0),
            ('line', 3, -6, 9, 0),
            ('line', 9, 0, 3, 6),
            ('line', 9, -6, 15, 0),
            ('line', 15, 0, 9, 6),
        ],
        'ports': {
            '1': {'x': -27, 'y': 0, 'direction': 'in'},
            '2': {'x': 27, 'y': 0, 'direction': 'out'},
        },
        'fields': {
            'ОУ': {'x': -6.418, 'y': -19.088},
            'В1': {'x': 17.582, 'y': 4.912},
            'В2': {'x': -33.418, 'y': 4.912},
        },
    },
    'sc_switch_3pos': {
        'title': 'Переключатель 3-позиционный',
        'prefix': 'SA',
        'source': 'Переключатель 3-позиционный',
        'bbox': (-27, -12, 27, 12),
        'primitives': [
            ('circle', 0, 0, 3),
            ('line', -27, 0, -18, 0),
            ('line', 18, 0, 27, 0),
            ('line', -18, -12, -18, 12),
            ('line', -6, -12, -6, 12),
            ('line', 0, -12, 0, 12),
            ('line', 6, -12, 6, 12),
            ('line', 18, -12, 18, 12),
        ],
        'ports': {
            'left': {'x': -27, 'y': 0, 'direction': 'in'},
            'right': {'x': 27, 'y': 0, 'direction': 'out'},
        },
    },
}
