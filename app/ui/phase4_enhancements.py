from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut

from app.widgets.global_search_dialog import GlobalSearchDialog
from app.widgets.professional_status_bar import ProfessionalStatusBar
from app.widgets.toast_notification import show_toast


def install_phase4_enhancements(main_window):
    """Install ARC3 Phase 4 components once."""

    if getattr(main_window, "_arc3_phase4_installed", False):
        return

    main_window._arc3_phase4_installed = True

    install_notification_handler(main_window)
    install_status_bar(main_window)
    install_global_search(main_window)
    install_refresh_shortcut(main_window)
    schedule_startup_notification(main_window)


def install_notification_handler(main_window):
    """Expose a reusable notification function on the main window."""

    if hasattr(main_window, "show_arc3_notification"):
        return

    def show_notification(
        message,
        notification_type="info",
        duration=3500,
    ):
        return show_toast(
            main_window,
            message,
            notification_type,
            duration,
        )

    main_window.show_arc3_notification = show_notification


def schedule_startup_notification(main_window):
    """Schedule the ARC3 startup toast once."""

    if getattr(
        main_window,
        "_arc3_startup_toast_scheduled",
        False,
    ):
        return

    main_window._arc3_startup_toast_scheduled = True

    QTimer.singleShot(
        700,
        lambda: _show_startup_notification(main_window),
    )


def _show_startup_notification(main_window):
    """Display the startup toast if notifications are available."""

    notification = getattr(
        main_window,
        "show_arc3_notification",
        None,
    )

    if notification is not None:
        notification(
            "ARC3 professional interface is ready.",
            "success",
            3200,
        )


def install_status_bar(main_window):
    """Install one professional status bar."""

    if not hasattr(main_window, "setStatusBar"):
        return None

    existing = getattr(
        main_window,
        "arc3_status_bar",
        None,
    )

    if existing is not None:
        return existing

    status_bar = ProfessionalStatusBar(main_window)
    main_window.setStatusBar(status_bar)

    main_window.arc3_status_bar = status_bar

    return status_bar


def install_global_search(main_window):
    """Install the global search dialog and Ctrl+K shortcut."""

    existing_dialog = getattr(
        main_window,
        "arc3_search_dialog",
        None,
    )

    existing_shortcut = getattr(
        main_window,
        "arc3_search_shortcut",
        None,
    )

    if (
        existing_dialog is not None
        and existing_shortcut is not None
    ):
        return existing_dialog

    search_dialog = GlobalSearchDialog(main_window)

    shortcut = QShortcut(
        QKeySequence("Ctrl+K"),
        main_window,
    )

    shortcut.activated.connect(search_dialog.exec)

    main_window.arc3_search_dialog = search_dialog
    main_window.arc3_search_shortcut = shortcut

    return search_dialog


def install_refresh_shortcut(main_window):
    """Install one F5 refresh shortcut."""

    existing = getattr(
        main_window,
        "arc3_refresh_shortcut",
        None,
    )

    if existing is not None:
        return existing

    shortcut = QShortcut(
        QKeySequence("F5"),
        main_window,
    )

    shortcut.activated.connect(
        lambda: refresh_visible_page(main_window)
    )

    main_window.arc3_refresh_shortcut = shortcut

    return shortcut


def refresh_visible_page(main_window):
    """Refresh the currently visible ARC3 page or tab."""

    page_stack = getattr(
        main_window,
        "pages",
        None,
    )

    candidates = []

    current_page = None

    current_widget = getattr(
        page_stack,
        "currentWidget",
        None,
    )

    if callable(current_widget):
        current_page = current_widget()

    if current_page is not None:
        candidates.append(current_page)

    tab_widget = getattr(
        current_page,
        "tabs",
        None,
    )

    current_tab_getter = getattr(
        tab_widget,
        "currentWidget",
        None,
    )

    if callable(current_tab_getter):
        current_tab = current_tab_getter()

        if current_tab is not None:
            candidates.insert(0, current_tab)

    refresh_methods = (
        "refresh",
        "refresh_data",
        "refresh_processes",
        "refresh_information",
        "load_data",
        "reload",
    )

    for candidate in candidates:
        for method_name in refresh_methods:
            method = getattr(
                candidate,
                method_name,
                None,
            )

            if callable(method):
                method()

                notification = getattr(
                    main_window,
                    "show_arc3_notification",
                    None,
                )

                if notification is not None:
                    notification(
                        "Current view refreshed.",
                        "success",
                        1800,
                    )

                return True

    notification = getattr(
        main_window,
        "show_arc3_notification",
        None,
    )

    if notification is not None:
        notification(
            "This page does not have a refresh action.",
            "info",
            2200,
        )

    return False
