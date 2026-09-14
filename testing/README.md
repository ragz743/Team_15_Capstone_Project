# Project Testing

## Running Tests
- make sure you have activated your python virtual environment and installed packages
    - see code/README.md for details on how to set up project
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
pytest testing/backend/ --cov=code/backend --cov-report=html
```

Then open the report:

```bash
open htmlcov/index.html
```

The coverage report will show which parts of `code/backend` are covered by the unit tests.

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
