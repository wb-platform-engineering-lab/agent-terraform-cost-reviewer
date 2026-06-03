"""Backward-compatibility shim. The package entry point is terraform_cost_reviewer.cli."""
from terraform_cost_reviewer.cli import main

if __name__ == "__main__":
    main()
