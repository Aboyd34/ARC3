from PySide6.QtCore import QSettings


class AppSettings:
    def __init__(self):
        self.settings = QSettings("ARC3", "ARC3 Toolkit")

    def get_theme(self):
        return self.settings.value("appearance/theme", "dark")

    def set_theme(self, theme_name):
        self.settings.setValue("appearance/theme", theme_name)

    def get_geometry(self):
        return self.settings.value("window/geometry")

    def set_geometry(self, geometry):
        self.settings.setValue("window/geometry", geometry)

    def clear_geometry(self):
        self.settings.remove("window/geometry")

    def sync(self):
        self.settings.sync()
