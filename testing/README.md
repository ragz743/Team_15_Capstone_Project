# Project Testing

## Running Tests
- make sure you have activated your python virtual environment and installed packages
    - see code/README.md for details on how to set up project
- call command `pytest` from the command line to run all tests
    - test discovery configured in `pyproject.toml`

## Adding New Tests
- within reason, please do :)
- please use pytest

## Logging
Certain tests such as those in `workflow/test_workflow.py` utilize logging to track events during the program. To enable logging with pytest, make sure to add the correct flags. The following pytest call will enable logging (and overwrite the contents of the file in 'w' mode) and also show test output in stdout.
```Bash
python -m pytest ./testing/backend/workflow/test_workflow.py -s \
    --log-file=test_workflow.log \
    --log-file-mode=w
```
