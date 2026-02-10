# How to Run Tests

This backend uses `pytest` for unit tests.

## Prerequisites
- Python installed
- Dependencies installed (including `pytest`)

If you do not have `pytest` yet:
```bash
python -m pip install -r requirements.txt
# or, if requirements.txt is missing
python -m pip install pytest
```
For async tests, ensure `pytest-asyncio` is installed (included in requirements.txt).

## Run All Tests
```bash
python -m pytest
```

## Run a Single File
```bash
python -m pytest tests/test_vs_rules.py
```

## Run a Single Test
```bash
python -m pytest tests/test_vs_rules.py -k test_can_sabotage_respects_cooldown_and_last_30s
```

## Notes
- These are **unit tests**, so they do not require Redis.
- If you want integration tests against Redis, we can add a separate test suite and CI target.
