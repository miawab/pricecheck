"""Check that everything pricecheck needs is installed, and say how to fix what isn't.

    python -m pricecheck.doctor
"""
import importlib
import os
import shutil
import subprocess
import sys

from .recipe import ROOT

OK, BAD, INFO = "  [ok]  ", "  [!!]  ", "  [..]  "
problems = 0


def report(ok, msg, fix=None):
    global problems
    print((OK if ok else BAD) + msg)
    if not ok:
        problems += 1
        if fix:
            print("        -> " + fix)


def main():
    print("pricecheck setup check\n")

    report(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}", "Install Python 3.11 or newer from python.org")

    missing = [m for m in ["tabpfn", "ollama", "pandas", "sklearn", "requests", "fastapi", "uvicorn"]
               if importlib.util.find_spec(m) is None]
    report(not missing, "Python packages" + (f" (missing: {', '.join(missing)})" if missing else ""),
           "pip install -r requirements.txt")

    model = os.environ.get("PRICECHECK_MODEL", "gemma4:e4b-it-qat")
    try:
        import ollama
        names = [m.model for m in ollama.list().models]
        report(True, "Ollama is running")
        report(model in names, f"Gemma model {model}",
               f"ollama pull {model}   (about 6 GB; on a weaker PC use gemma4:e2b-it-qat and set PRICECHECK_MODEL in .env)")
    except Exception:
        report(False, "Ollama is running", "Install Ollama from https://ollama.com, open it, then run this check again")

    if shutil.which("nvidia-smi"):
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True).stdout.strip()
        print(INFO + f"GPU: {gpu} (Gemma will use it)")
    else:
        print(INFO + "No NVIDIA GPU found: Gemma will run on the CPU, slower (a minute or more per listing)")

    report(bool(os.environ.get("TABPFN_TOKEN")), "TabPFN key in .env",
           "Sign up free at https://ux.priorlabs.ai, accept the license on the Licenses tab, copy your API key "
           "from the Account page, and add a line TABPFN_TOKEN=<your key> to .env")

    recipes = sorted(p.stem for p in (ROOT / "recipes").glob("*.toml") if not p.stem.endswith(".draft"))
    report(bool(recipes), f"Recipes: {', '.join(recipes) or 'none'}",
           'Make one: python -m pricecheck.new_recipe phones "https://www.olx.com.pk/mobile-phones_c1453"')
    for r in recipes:
        has_data = (ROOT / "site" / "data" / f"{r}.json").exists()
        print(INFO + f"{r}: " + ("has data, ready to view" if has_data else
                                   f"no data yet -> python -m pricecheck.update {r} --limit 100"))

    print()
    if problems:
        print(f"{problems} thing(s) to fix above, then run this check again.")
    else:
        print("All set. Start the page with:  python -m pricecheck.app   then open http://localhost:8000")


if __name__ == "__main__":
    main()
