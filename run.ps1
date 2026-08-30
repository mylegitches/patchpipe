Set-Location $PSScriptRoot
python -m pip install -e . -q 2>$null
python -m patchpipe.cli --lan @args
