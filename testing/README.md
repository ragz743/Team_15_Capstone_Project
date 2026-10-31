# Project Testing

## Running Tests
- make sure you have activated your python virtual environment and installed packages
    - see code_/README.md for details on how to set up project
- call command `pytest` from the command line to run all tests
    - test discovery configured in `pyproject.toml`

## Adding New Tests
- within reason, please do :)
- please use pytest

## Details about Testing Setup

This will explain how to install the testing dependencies and run the unit and end-to-end tests.

## 1. Install Development Dependencies

From the project root, run:

```bash
pip install -e ".[dev]"
```

Alternatively, you can install the testing packages directly:

```bash
pip install pytest pytest-httpx pytest-cov pytest-html requests
```

## 2. Run Unit Tests

Run all backend unit tests:

```bash
pytest testing/backend/ -v
```

The `-v` flag enables verbose output so you can see each test result!

### Run Unit Tests with Coverage

To generate an HTML coverage report:

```bash
pytest testing/backend/ --cov=code_/backend --cov-report=html
```

Then open the report:

```bash
open htmlcov/index.html
```

The coverage report will show which parts of `code_/backend` are covered by the unit tests.

## 3. Run E2E Tests

**Docker must be running before starting the E2E tests.**

First, start the required services:

```bash
docker compose up -d
```

Then run the E2E tests and generate an HTML report:

```bash
pytest testing/e2e/ -v --html=reports/e2e_report.html --self-contained-html
```

After the tests finish, open the report:

```bash
open reports/e2e_report.html
```

The E2E report contains the test results and details for each test.                                              |

If you have any questions or run into issues, feel free to ask!

## PR 90 checks

Run backend checks with local PostgreSQL and disposable schemas:

```bash
RUN_PGVECTOR_TESTS=1 pytest testing/backend \
  --ignore=testing/backend/test_awn_connection.py \
  --ignore=testing/backend/test_model_factory.py \
  -k 'not test_nearest_station_search'
```

The excluded AWN connection and model factory checks require their configured external
services. Run `npm test`, `npm run lint` and `npm run build` from `code_/frontend`.

Controlled model outputs verify interpretation contracts and routing. They do not measure
live language accuracy. Startup checks verify migration failure stops the API.

For live interpretation and saved chat checks, select an available free model that supports
structured output. For example:

```bash
OPENROUTER_CHAT_MODEL=dots-studio/dots-3-note-preview:free \
OPENROUTER_HISTORY_MODEL=dots-studio/dots-3-note-preview:free \
RUN_WEATHER_MODEL_TESTS=1 RUN_HISTORY_MODEL_TESTS=1 RUN_HISTORY_RUNTIME_TESTS=1 \
pytest testing/e2e/test_weather_language.py \
  testing/e2e/test_history_language.py testing/e2e/test_history_runtime.py
```

These checks send synthetic messages. The API checks use disposable PostgreSQL schemas
and controlled weather records with live model interpretation and answer generation.
They cover recall, saved location reuse, failed retrieval retries, reloads and ownership.
They do not query the external AWN database. Provider failures remain failed checks.

For browser checks, build the frontend and run
`PYTHONPATH=code_:testing python testing/pr90_browser_fixture.py --env-file .env`.
With Playwright and Chrome available, run `node testing/pr90_browser.cjs` in another
terminal. The fixture uses a disposable PostgreSQL schema and removes it on shutdown.
## Logging
Certain tests such as those in `workflow/test_workflow.py` utilize logging to track events during the program. To enable logging with pytest, make sure to add the correct flags. The following pytest call will enable logging (and overwrite the contents of the file in 'w' mode) and also show test output in stdout.
```Bash
python -m pytest ./testing/backend/workflow/test_workflow.py -s \
    --log-file=test_workflow.log \
    --log-file-mode=w
```
> Note: When running tests which make calls to an LLM, such as the sample questions suite, an extra argument is needed! This is done to prevent accidental runs which will consume project LLM budget. To run these tests w/ logging use:
```Bash
python -m pytest ./testing/backend/workflow/test_workflow.py -s \
    --log-file=test_workflow.log \
    --log-file-mode=w \
    --run-sample-questions
```
