# Шкафы стандарта по UML-модели EA

Собрано: 2026-11-11 19:43

| Источник | Файл |
| --- | --- |
| UML-схема (XMI) | `EA/structure.xml` |
| Стандарт | `EA/Раздел 4.16_т. 5_СТО ШЭТ СКРМ II_Ред.2.docx` |
| Результат | `EA/cabinets_uml.json` |

Модель: **классов — 23, атрибутов — 88, ассоциаций — 23**. Имена полей в JSON совпадают с атрибутами XMI; вложенность повторяет связи классов. В XMI два элемента `TerminalRow` (дубликат с атрибутом `Location`), поэтому уникальных имён классов на один меньше.

## Шкафы

| Раздел | Шифр | Наименование | Комплекты / ИЭУ | Функций | Сигналов | Клемм |
| --- | --- | --- | --- | --- | --- | --- |
| 5.3 | ШЭТ 431.11-1 | Шкаф защит батареи статических конденсаторов 110–330 кВ, УРОВ | 1 / 1 | 25 | 387 | 39 |
| 5.4 | ШЭТ 431.12-1 | Шкаф защит шунтирующего реактора 330–750 кВ, УРОВ | 1 / 1 | 52 | 626 | 42 |
| 5.5 | ШЭТ 431.13-1 | Шкаф защит шунтирующего реактора 110–220 кВ, УРОВ | 1 / 1 | 48 | 522 | 38 |
| 5.6 | ШЭТ 431.14-1 | Шкаф защит и автоматики компенсационного реактора 35–110 кВ, УРОВ, АКР | 1 / 1 | 14 | 253 | 10 |

## Покрытие UML-классов

| Класс | Объектов | Заполнено атрибутов | Не заполнено |
| --- | ---: | --- | --- |
| `AnalogInput` | 30 | `circuit_type`, `test_block`, `contacts_count`, `note` | — |
| `Cabinet` | 4 | `cypher`, `architecture`, `name`, `controllable_element`, `protected_element`, `scope`, `description`, `standard` | — |
| `CabinetReport` | 4 | `cab_cypher`, `architecture`, `cab_name`, `components`, `controllable_element`, `protected_element` | — |
| `Component` | 44 | `name`, `description`, `quantity` | — |
| `ControlCommand` | 43 | `name`, `info_model` | — |
| `DataSet` | 27 | `mapping`, `name`, `class`, `sender`, `id`, `note` | — |
| `Function` | 139 | `name`, `isMainFunction`, `isInITS` | `iec_name`, `russian_path` |
| `FunctionalButton` | 41 | `mapping`, `short_name`, `disable_condition`, `enable_condition` | — |
| `IED` | 4 | `number` | — |
| `IncomingGooseSignal` | 128 | `signal`, `info_model`, `source`, `max_number`, `RAS` | `note`, `source_number` |
| `InnerDiscreteCircuit` | 38 | `discrete_signal`, `direction`, `note` | — |
| `Kit` | 4 | `number`, `description` | — |
| `LED` | 72 | `mapping`, `name`, `mode` | `note` |
| `OscAnalogSignal` | 140 | `description`, `name`, `startRAS` | `canal` |
| `OutcomingMessage` | 8 | — | — |
| `OutcomingReport` | 19 | `mapping`, `sender`, `id`, `message_class`, `note` | — |
| `Parameter` | 254 | `name`, `description`, `conditions` | — |
| `PowerSupply` | 12 | `purpose` | — |
| `Signal` | 1788 | `name`, `info_model`, `destination`, `status`, `KT`, `cus`, `rdu`, `RAS`, `DO`, `DA` | `note` |
| `Terminal` | 129 | `number`, `quantity`, `function_type`, `connection_type`, `purpose` | — |
| `TerminalBlock` | 46 | `text` | — |
| `TerminalRow` | 46 | `location` | `Location` |
| `port` | 8 | `description` | — |

## Соответствие таблиц стандарта и классов UML

| Подпись таблицы (раздел 5.N) | Классы / блок |
| --- | --- |
| Входные аналоговые измерения… | `AnalogInput` |
| Внутренние дискретные цепи… | `InnerDiscreteCircuit` |
| Информационные сигналы в составе входящих сообщений… | `IncomingGooseSignal` |
| Функциональные клавиши… | `FunctionalButton` |
| Светодиодная сигнализация… | `LED` |
| Сообщения и отчеты, исходящие от ИЭУ… | `DataSet/OutcomingMessage/OutcomingReport` |
| Информационные сигналы в составе исходящих сообщений… | `Signal (GOOSE)` |
| Информационные сигналы в составе исходящих отчетов… | `Signal (отчёты)` |
| Осциллографируемые аналоговые сигналы… | `OscAnalogSignal` |
| Команды управления от АСУ ТП… | `ControlCommand` |
| Основные параметры функций РЗА… | `Function/Parameter` |
| Ряды зажимов… | `TerminalBlock/TerminalRow/Terminal` |
| Основные компоненты шкафа… | `Component` |
| Описание ШЭТ… | `Cabinet/PowerSupply/port/Kit` |

Карточка «Описание ШЭТ» даёт `Cabinet` (шифр, архитектура, наименование, управляемый/защищаемый элементы, область применения), `PowerSupply`, `port`, `Kit`, первый абзац раздела — `Cabinet.description`. `CabinetReport` — сводная карточка с `components`. Поле `Cabinet.standard` содержит имя файла исходного стандарта без расширения (Раздел 4.16_т. 5_СТО ШЭТ СКРМ II_Ред.2) — оно одинаково у всех шкафов тома и позволяет отличать выгрузки разных томов при сборке новых шкафов.

## Оговорки

* В XMI два класса `TerminalRow` (атрибуты `location` и `Location`), а композитные концы связей `Kit`/`TerminalRow`/`TerminalBlock`/`Terminal` образуют кольцо. Использована иерархия самой таблицы «Ряды зажимов»: `Kit.TerminalBlock → TerminalRow → Terminal`; `TerminalRow.location` — маркировка колодки из строки-заголовка.
* `OutcomingMessage` в UML не имеет атрибутов, только связь с `DataSet`: строки GOOSE таблицы «Сообщения и отчеты…» стали контейнерами, а sender / id / class / note лежат во вложенном `DataSet`. Отчёты `dsrpt_*` лежат непосредственно в `IED.DataSet` (по связи IED → DataSet), а их описания — в `IED.OutcomingReport`.
* `Function.isMainFunction` / `isInITS` выведены из полей «Основные функции» и «Функции ИТС [14]» карточки: для групп таблицы 5.N.13 берётся самое длинное совпадение кода, функции без группы добавлены отдельно. Обозначения со скобками («ДТЗ СО (ДЗР ШР)») раскрываются в синонимы, чтобы оба списка сопоставлялись; группы «Параметры ТН/ТТ», «КСВ», «ЛО …», «ЗПО» и т.п. в перечнях карточки не значатся и получают `false / false`. Атрибуты `iec_name` и `russian_path` в стандарте отсутствуют и не записаны.
* Значения «» («то же, что выше») развёрнуты по столбцу, пустые ячейки и строки-заголовки («Имя набора данных», «Сообщения», «Отчеты», примечания) в объекты не превращаются. Строки «Разделитель цепи» в таблице рядов зажимов не являются клеммами и пропущены.
* Набор `dsrpt_DR` («Данные РАС») заявлен в таблице сообщений, но отдельной таблицы сигналов для него в разделе нет — `DataSet` создан без `Signal`.
* `Signal.info_model` для отчётов собран из `DO.DA`, сами `DO` и `DA` сохранены отдельно; `destination` есть только у GOOSE-сигналов.
* Атрибутов, для которых в таблицах стандарта нет колонок, в JSON нет: `Function.iec_name`, `Function.russian_path`, `LED.note`, `Signal.note`, `IncomingGooseSignal.note`, `IncomingGooseSignal.source_number`, `OscAnalogSignal.canal` (столбец «Канал» в документе пуст).
* Проверка результата по модели: **ошибок нет**.
* Пропущено при разборе: строки-разделители цепей (не клеммы) — 8.

### Замечания парсера DOCX

* титул: таблица без подписи пропущена (УТВЕРЖДАЮ; Генеральный директор; ООО «Юнител Инжиниринг»; __…)
* титул: таблица без подписи пропущена (Руководитель работы)
* Предисловие: таблица без подписи пропущена (1. РАЗРАБОТАН:)
* Сокращения: таблица без подписи пропущена (DA)
* Система кодирования типовых шкафов: таблица без подписи пропущена (ШЭТ ХХХ.ХХ - X - XXXX)
* Библиография: таблица без подписи пропущена (СТО 56947007-29.120.70.241-2017)

## Повторить

```bash
python3 tools/docx_to_uml.py
python3 tools/docx_to_uml.py --docx "EA/Раздел 4.16_т. 5_СТО ШЭТ СКРМ II_Ред.2.docx"
```
