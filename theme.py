"""Визуальная система «Татнефть»: палитра, plotly-шаблон и темизация фигур.

Единственный источник цветов/токенов для app.py и gtm_analysis.py —
раньше каждый модуль держал свою копию, и они начинали расходиться.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# -----------------------------------------------------------------------------
# Палитра (снята с презентационного шаблона Группы «Татнефть»)
# -----------------------------------------------------------------------------
OP_BG = "#F7F8F5"
OP_CARD = "#FFFFFF"
OP_CARD2 = "#F1F5EF"
OP_BORDER = "#DDE7E1"
OP_GRID = "#E5EDE8"
OP_INK = "#1F2B25"
OP_MUTED = "#6F7D76"
OP_GREEN = "#008E5B"
OP_GREEN_DEEP = "#006B45"
OP_GREEN_LIGHT = "#C5E5D7"
OP_AMBER = "#F2B84B"
OP_RED = "#D53033"
PALETTE = [OP_GREEN, "#00B473", OP_RED, "#7CB342", "#44546A", OP_AMBER, "#7E8C86", "#B8D9CC", OP_GREEN_DEEP]
HEAT_SCALE = [[0.0, "#EEF5F1"], [0.45, OP_GREEN_LIGHT], [0.75, OP_GREEN], [1.0, OP_RED]]

# Дополнительные цвета для графика технологической динамики
TN_LIQ_GREEN = "#008E5B"      # добыча жидкости
TN_OIL_BURGUNDY = "#7A1F2B"   # добыча нефти
TN_INJ_BLUE = "#1F77B4"       # закачка
TN_WC_CYAN = "#45B8D8"        # обводнённость
TN_DEBIT_LIQ_PURPLE = "#7E57C2"
TN_DEBIT_OIL_RED = "#D53033"
TN_FUND_BLUE = "#2F80ED"

FONT_BODY = "Montserrat, Segoe UI, Arial, sans-serif"
FONT_MONO = "Montserrat, Segoe UI, Arial, sans-serif"

DARK_TOKENS = {
    "card": "#17211D",
    "paper": "#101815",
    "ink": "#E8F0EC",
    "muted": "#A8B9B0",
    "border": "#314138",
    "grid": "rgba(168, 185, 176, 0.16)",
    "legend_bg": "rgba(23,33,29,0)",
    "hover_bg": "#1F2B26",
}

THEME_TOKENS = {
    "light": {
        "card": OP_CARD,
        "ink": OP_INK,
        "muted": OP_MUTED,
        "border": OP_BORDER,
        "grid": OP_GRID,
        "legend_bg": "rgba(255,255,255,0)",
        "hover_bg": "#FFFFFF",
    },
    "dark": DARK_TOKENS,
}


def register_templates() -> None:
    """Регистрирует plotly-шаблон tatneft_light и делает его дефолтным."""
    pio.templates["tatneft_light"] = go.layout.Template(
        layout=go.Layout(
            font=dict(family=FONT_BODY, color=OP_INK, size=12),
            paper_bgcolor=OP_CARD,
            plot_bgcolor=OP_CARD,
            colorway=PALETTE,
            margin=dict(l=62, r=28, t=62, b=58),
            title=dict(font=dict(size=14, color=OP_GREEN, family=FONT_BODY), x=0.0, xanchor="left", yanchor="top", y=0.98),
            xaxis=dict(showgrid=False, zeroline=False, linecolor=OP_BORDER, tickcolor=OP_BORDER, tickfont=dict(family=FONT_BODY, size=10.5, color=OP_MUTED), title=dict(font=dict(color=OP_MUTED))),
            yaxis=dict(showgrid=True, gridcolor=OP_GRID, zeroline=False, linecolor=OP_BORDER, tickcolor=OP_BORDER, tickfont=dict(family=FONT_BODY, size=10.5, color=OP_MUTED), title=dict(font=dict(color=OP_MUTED))),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10.5, color=OP_MUTED), bgcolor="rgba(255,255,255,0)"),
            hoverlabel=dict(bgcolor="#FFFFFF", bordercolor=OP_GREEN, font=dict(color=OP_INK, family=FONT_BODY, size=11)),
            colorscale=dict(sequential=HEAT_SCALE),
        )
    )
    pio.templates.default = "tatneft_light"


def normalize_theme(theme: str | None) -> str:
    return "dark" if theme == "dark" else "light"


def rgba_from_hex(color, alpha):
    if not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
        return color
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


def apply_runtime_theme(fig, theme: str | None = "light", tokens_map=None, font_family: str = FONT_BODY, templates=None):
    """Перекрашивает готовую фигуру под светлую/тёмную тему.

    tokens_map позволяет модулю передать собственные light-токены
    (например, вкладка ГТМ), tемплейты — переключить базовый plotly-шаблон.
    """
    theme_name = normalize_theme(theme)
    tokens = (tokens_map or THEME_TOKENS)[theme_name]
    themed = go.Figure(fig)
    layout_kwargs = dict(
        paper_bgcolor=tokens["card"],
        plot_bgcolor=tokens["card"],
        font=dict(family=font_family, color=tokens["ink"], size=12),
        legend=dict(
            font=dict(color=tokens["muted"]),
            bgcolor=tokens["legend_bg"],
            bordercolor=tokens["border"],
        ),
        hoverlabel=dict(
            bgcolor=tokens["hover_bg"],
            bordercolor=OP_GREEN,
            font=dict(color=tokens["ink"], family=font_family, size=11),
        ),
    )
    if templates:
        layout_kwargs["template"] = templates[theme_name]
    themed.update_layout(**layout_kwargs)
    axis_names = [
        axis_name
        for axis_name in themed.to_plotly_json().get("layout", {})
        if axis_name.startswith(("xaxis", "yaxis"))
    ]
    for axis_name in axis_names:
        themed.update_layout(
            **{
                axis_name: dict(
                    gridcolor=tokens["grid"],
                    linecolor=tokens["border"],
                    tickcolor=tokens["border"],
                    tickfont=dict(color=tokens["muted"]),
                    title=dict(font=dict(color=tokens["muted"])),
                )
            }
        )
    for annotation in themed.layout.annotations or ():
        annotation.update(font=dict(color=tokens["muted"]))
    return themed


def apply_theme(fig, height=None, compact=False):
    # Высота задаётся одновременно контейнеру dcc.Graph и Plotly layout.
    # Заголовки внутри Plotly не используем: название уже есть в шапке карточки.
    layout_kwargs = dict(
        template="tatneft_light",
        autosize=True,
        title=None,
        margin=dict(l=62, r=34, t=30, b=74),
    )
    if compact:
        layout_kwargs.update(
            margin=dict(l=54, r=22, t=24, b=58),
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.24,
                xanchor="left",
                x=0,
                font=dict(size=9.5, color=OP_MUTED),
                bgcolor="rgba(255,255,255,0)",
                itemwidth=30,
            ),
        )
    if height is not None:
        layout_kwargs["height"] = int(str(height).replace("px", ""))
    fig.update_layout(**layout_kwargs)
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


def empty_fig(title="Нет данных", height=None):
    fig = go.Figure()
    fig.add_annotation(text=title, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(size=14, color=OP_MUTED))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_theme(fig, height=height)


def sparkline(x, y, color=OP_GREEN):
    fig = go.Figure(go.Scatter(x=list(x), y=list(y), mode="lines", line=dict(color=color, width=2), fill="tozeroy", hoverinfo="skip"))
    if color.startswith("#") and len(color) == 7:
        fig.update_traces(fillcolor=rgba_from_hex(color, 0.12))
    fig.update_layout(
        height=46,
        margin=dict(l=0, r=0, t=2, b=0),
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="rgba(255,255,255,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
    )
    return fig


register_templates()
