"""Колбэки переключения светлой/тёмной темы."""

from __future__ import annotations

from dash import Input, Output, State

from theme import normalize_theme


def register(app):
    @app.callback(
        Output("theme-store", "data"),
        Input("theme-toggle", "n_clicks"),
        State("theme-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_theme(_clicks, current_theme):
        return "light" if normalize_theme(current_theme) == "dark" else "dark"


    @app.callback(
        Output("app-shell", "className"),
        Output("theme-toggle", "children"),
        Output("theme-toggle", "title"),
        Input("theme-store", "data"),
    )
    def apply_app_theme(theme):
        theme_name = normalize_theme(theme)
        is_dark = theme_name == "dark"
        return (
            f"shell theme-{theme_name}",
            "Светлая тема" if is_dark else "Темная тема",
            "Переключить на светлую тему" if is_dark else "Переключить на темную тему",
        )

    # Мгновенно сообщаем iframe консоли LiteLLM о смене темы через postMessage,
    # чтобы ей не приходилось опрашивать localStorage по таймеру.
    app.clientside_callback(
        """
        function(theme) {
            var frames = document.querySelectorAll("iframe.litellm-console-frame");
            frames.forEach(function(frame) {
                try {
                    frame.contentWindow.postMessage(
                        {type: "dashboard-theme", theme: theme === "dark" ? "dark" : "light"},
                        window.location.origin
                    );
                } catch (e) {}
            });
            return "";
        }
        """,
        Output("theme-broadcast", "children"),
        Input("theme-store", "data"),
    )

