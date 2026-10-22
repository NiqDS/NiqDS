# Проверки к разбору `docs/split_homogeneity_review_ru.md`

Три скрипта, которыми получены числа из разбора. Запускать вне скилла —
им нужны `numpy scipy pandas scikit-learn` (в `requirements.txt` скилла их
нет намеренно: сам скилл работает на стандартной библиотеке).

```bash
pip install numpy scipy pandas scikit-learn
python3 -I docs/analysis/stratification_sim.py   # доля клиентов в rare_strats
python3 -I docs/analysis/power_check.py          # p-value против размера пилота
python3 -I docs/analysis/homogeneity_checks.py   # 18 тестов + ререндомизация
```

`stratification_sim.py` воспроизводит код из тетрадки дословно по поведению,
на синтетической популяции ММБ. Чтобы проверить на своих данных, замените
`population()` на чтение реального `features` — остальное менять не нужно.
