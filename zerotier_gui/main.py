import sys

from PyQt6.QtWidgets import QApplication

from .tray_app import TrayApp


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray = TrayApp(app)
    tray.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

