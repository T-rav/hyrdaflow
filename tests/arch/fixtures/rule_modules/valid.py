from hydraflow.arch import Allowlist, Fitness, LayerMap, python_ast_extractor

EXTRACTOR = python_ast_extractor
LAYERS = LayerMap({"src/a/**": 1})
ALLOWLIST = Allowlist({})
FITNESS = [Fitness.max_lines("src/**/*.py", 600)]
