import os

from addictune_cli.src.subprocess_worker import ENV_KEY

if __name__ == "__main__":
    match os.environ.get(ENV_KEY):
        case "player":
            from addictune_cli.src.audio.worker import main
            main()
        case _:
            from addictune_cli.src.main import main
            main()
