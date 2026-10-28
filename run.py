"""Windows entry point; also supports headless receiver for integration tests."""
import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import time
from coach02 import config
from coach02.service import Service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-mode', action='store_true')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--data-dir', type=Path, default=config.data_dir())
    args = parser.parse_args()
    directory = args.data_dir
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[RotatingFileHandler(directory/'app.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')])
    service = None
    try:
        settings = config.load(directory)
        (directory/config.GSI_FILENAME).write_text(config.gsi_text(settings), encoding='utf-8')
        service = Service(directory, settings, test_mode=args.test_mode)
        service.start()
        if args.headless:
            print(f'GSI listening on 127.0.0.1:{settings["port"]}', flush=True)
            while True:
                time.sleep(1)
        else:
            import tkinter as tk
            from coach02.ui import Window
            import os
            if os.name == 'nt':
                import ctypes
                try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception: pass
            root = tk.Tk()
            Window(root, service)
            root.mainloop()
            service = None  # Window owns normal shutdown.
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logging.exception('Falha ao iniciar')
        print(f'Erro: {exc}\nDetalhes: {directory / "app.log"}', file=sys.stderr)
        if not args.headless:
            try:
                from tkinter import messagebox
                messagebox.showerror('Dota AI Coach', f'{exc}\n\nConsulte {directory / "app.log"}\nSe a porta está em uso, feche outra instância do Coach.')
            except Exception:
                pass
        return 1
    finally:
        if service:
            service.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
