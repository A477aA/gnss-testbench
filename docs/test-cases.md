# Тест-кейсы и трассировка на автотесты

Каждый тест-кейс связан с автотестом: так видно, что требование покрыто и где его проверка.

## Приём и разбор

| ID | Приоритет | Проверка | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-01 | High | Эталонные строки GGA/RMC/GSA/GSV/VTG | Разобраны без ошибок, поля совпадают с эталоном | `test_framing::test_reference_sentences_are_valid`, `test_sentences::test_*_reference` |
| TC-02 | High | Искажение одного символа | `ChecksumError` | `test_framing::test_broken_sentences_rejected`, `test_fuzz::test_any_single_byte_corruption_is_detected` |
| TC-03 | High | Координаты на границах: 0°, ±90°, ±180° | Корректный знак и значение | `test_fields::test_valid_coordinates` |
| TC-04 | High | Координаты за границей, минуты = 60 | `FieldError` | `test_fields::test_invalid_coordinates` |
| TC-05 | Medium | Время 23:59:59.99 и 24:00:00 | Первое валидно, второе — ошибка | `test_fields::test_time`, `test_invalid_time` |
| TC-06 | Medium | Двузначный год 79/80 | 2079 / 1980 | `test_fields::test_date` (BUG-001) |
| TC-07 | High | Решение заявлено, координаты пустые | `FieldError` | `test_sentences::test_gga_fix_without_coordinates_is_inconsistent` |
| TC-08 | Medium | GSV: угол места, азимут, SNR вне диапазона | `FieldError` | `test_sentences::test_gsv_invalid` |
| TC-09 | Low | Неизвестный тип сообщения | Пропускается без ошибки | `test_sentences::test_unsupported_sentence_returns_none` |
| TC-10 | High | Произвольный ввод | Только `NmeaError`, без падений | `test_fuzz::test_parser_never_crashes_*` |

## Поток с порта

| ID | Приоритет | Проверка | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-20 | High | Поток нарезан на куски от 1 байта | Результат не зависит от нарезки | `test_stream::test_chunking_does_not_matter`, `test_fuzz::test_decoder_is_chunking_invariant` |
| TC-21 | High | Бинарный мусор между строками | Строки целы, мусор посчитан | `test_stream::test_garbage_between_sentences_is_counted_and_skipped` |
| TC-22 | High | Строка оборвана новым `$` | Оборванная отброшена, следующая принята | `test_stream::test_truncated_sentence_detected_by_next_dollar` |
| TC-23 | Medium | Бесконечная строка без конца | Отброшена по длине, декодер восстановился | `test_stream::test_overlong_line_dropped_and_decoder_recovers` |
| TC-24 | Medium | Окончания строк CR, LF, CRLF, LFCR | Все принимаются | `test_stream::test_any_line_ending` |
| TC-25 | High | Передача через UART кусками 1/7/512 байт | Побайтное совпадение | `test_virtual_port::test_uart_fragmentation_does_not_lose_data` |
| TC-26 | Medium | Подключение к уже вещающему приёмнику | Теряется только начало, декодер работает | `test_virtual_port::test_data_sent_before_port_opened_is_lost` (BUG-003) |

## Метрики решения

| ID | Приоритет | Проверка | Ожидаемый результат | Автотест |
|---|---|---|---|---|
| TC-40 | High | TTFF и время до RTK fixed | Совпадают с моментами переходов | `test_metrics::test_ttff_and_time_to_rtk` |
| TC-41 | High | Пропуск эпох | Разрыв найден и учтён в доле RTK fixed; это не потеря фиксации | `test_metrics::test_gap_detected_and_counts_against_rtk_ratio` |
| TC-42 | High | Потеря RTK fixed | Посчитана каждая потеря с моментом времени | `test_metrics::test_downgrades_counted_per_loss` |
| TC-43 | High | Ложная фиксация (скачок на 0.8 м) | 2 скачка: туда и обратно | `test_metrics::test_position_jump_out_and_back` |
| TC-44 | High | CEP50/CEP95 на известных смещениях | 5.5 см / 9.55 см | `test_metrics::test_accuracy_known_offsets` |
| TC-45 | Medium | Переход через полночь UTC | Порядок эпох сохранён, ложного разрыва нет | `test_metrics::test_midnight_rollover_keeps_order` |
| TC-46 | Medium | Решения не было вовсе | Метрики пустые, критерий проваливается | `test_criteria_report::test_missing_metric_fails_check` |

## Приёмка (сквозные сценарии)

| ID | Сценарий | Критерии | Ожидание | Автотест |
|---|---|---|---|---|
| TC-60 | Открытое небо | `rtk_static` | Пройдена | `test_virtual_port::test_scenario_through_serial_port[open_sky_rtk]` |
| TC-61 | Помехи на UART | `serial_robustness` | Пройдена | `...[noisy_serial]` |
| TC-62 | Городской каньон | `rtk_static` | Провалена: срыв фиксации, скачки, CEP95 | `...[urban_canyon]` |
| TC-63 | Тоннель | `rtk_static` | Провалена: разрыв 12 с, потеря фиксации | `...[tunnel_dropout]` |
