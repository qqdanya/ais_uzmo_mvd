from calendar import monthrange
from datetime import date, timedelta
from math import ceil, floor, log10

from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from .admin_summary import (
    available_departments,
    available_organs_for_user,
    build_attention_requests,
    build_department_load,
    build_dynamics,
    build_kpi,
    build_org_chart,
    parse_period,
    request_tables,
    selected_departments,
    selected_organs,
    serialize_period,
    status_history_flags,
    table_base_metrics,
)


COMPARISON_CHOICES = (
    ("previous", "Предыдущий аналогичный период"),
    ("previous_year", "Тот же период прошлого года"),
    ("custom", "Произвольный период"),
    ("none", "Без сравнения"),
)
COMPARISON_KEYS = {key for key, _label in COMPARISON_CHOICES}
REPORT_METRICS = (
    ("total", "Поступило", True),
    ("done", "Исполнено", True),
    ("rejected", "Отклонено", True),
    ("in_work", "В работе на дату формирования", False),
    ("stale", "Просрочено на дату формирования", False),
)
GRANULARITY_LABELS = {
    "day": "по дням",
    "week": "по неделям",
    "month": "по месяцам",
    "year": "по годам",
}
CHART_METRIC_CHOICES = (
    ("incoming", "Поступившие"),
    ("done", "Исполненные"),
    ("rejected", "Отклонённые"),
)
CHART_METRIC_KEYS = {key for key, _label in CHART_METRIC_CHOICES}
CHART_LAYOUT_CHOICES = (
    ("combined", "На одном графике"),
    ("separate", "На двух графиках"),
)
CHART_LAYOUT_KEYS = {key for key, _label in CHART_LAYOUT_CHOICES}


def _period(date_from, date_to, label):
    return {
        "period": "comparison",
        "date_from": date_from,
        "date_to": date_to,
        "label": label,
    }


def _display_period(date_from, date_to):
    return f"{date_from:%d.%m.%Y} – {date_to:%d.%m.%Y}"


def _shift_year(day):
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def _is_full_month(date_from, date_to):
    return (
        date_from.day == 1
        and date_to.day == monthrange(date_to.year, date_to.month)[1]
        and date_from.year == date_to.year
        and date_from.month == date_to.month
    )


def _is_full_year(date_from, date_to):
    return date_from == date(date_from.year, 1, 1) and date_to == date(date_from.year, 12, 31)


def previous_comparison_period(period):
    date_from = period.get("date_from")
    date_to = period.get("date_to")
    if not date_from or not date_to:
        return None
    if _is_full_year(date_from, date_to):
        previous_from = date(date_from.year - 1, 1, 1)
        previous_to = date(date_to.year - 1, 12, 31)
    elif _is_full_month(date_from, date_to):
        previous_to = date_from - timedelta(days=1)
        previous_from = previous_to.replace(day=1)
    else:
        duration = date_to - date_from + timedelta(days=1)
        previous_to = date_from - timedelta(days=1)
        previous_from = previous_to - duration + timedelta(days=1)
    return _period(previous_from, previous_to, _display_period(previous_from, previous_to))


def previous_year_comparison_period(period):
    date_from = period.get("date_from")
    date_to = period.get("date_to")
    if not date_from or not date_to:
        return None
    previous_from = _shift_year(date_from)
    previous_to = _shift_year(date_to)
    return _period(previous_from, previous_to, _display_period(previous_from, previous_to))


def comparison_period(period, mode, custom_date_from=None, custom_date_to=None):
    if mode == "none" or period.get("period") == "all":
        return None
    if mode == "custom" and custom_date_from and custom_date_to:
        date_from = min(custom_date_from, custom_date_to)
        date_to = max(custom_date_from, custom_date_to)
        return _period(date_from, date_to, _display_period(date_from, date_to))
    if mode == "previous_year":
        return previous_year_comparison_period(period)
    return previous_comparison_period(period)


def _change_values(current, previous):
    delta = current - previous
    if previous:
        percent = round(delta * 100 / previous, 1)
        percent_display = f"{percent:+.1f}%".replace(".", ",")
    elif current:
        percent = None
        percent_display = "новое значение"
    else:
        percent = 0
        percent_display = "0%"
    return delta, percent, percent_display


def report_metric_rows(
    current_kpi,
    comparison_kpi,
    current_days=None,
    comparison_days=None,
    show_daily_average=False,
):
    show_daily_average = bool(
        show_daily_average and comparison_kpi and current_days and comparison_days
    )
    rows = []
    for key, label, comparable in REPORT_METRICS:
        current = current_kpi.get(key, 0)
        previous = comparison_kpi.get(key, 0) if comparison_kpi and comparable else None
        row = {
            "key": key,
            "label": label,
            "current": current,
            "comparison": previous,
            "comparable": previous is not None,
            "period_metric": comparable,
        }
        if previous is not None:
            delta, percent, percent_display = _change_values(current, previous)
            row.update(
                {
                    "delta": delta,
                    "delta_display": f"{delta:+d}",
                    "percent": percent,
                    "percent_display": percent_display,
                }
            )
            if show_daily_average:
                row.update(
                    {
                        "show_daily_average": True,
                        "current_daily_display": f"{current / current_days:.1f}".replace(".", ","),
                        "comparison_daily_display": f"{previous / comparison_days:.1f}".replace(".", ","),
                    }
                )
        rows.append(row)
    return rows


def report_chart(
    dynamics,
    requested_granularity,
    comparison_dynamics=None,
    requested_metrics=None,
    requested_layout="combined",
    current_period_label="",
    comparison_period_label="",
):
    granularity = (
        requested_granularity
        if requested_granularity in GRANULARITY_LABELS
        else dynamics["default_granularity"]
    )
    series = dynamics[granularity]
    comparison_series = comparison_dynamics[granularity] if comparison_dynamics else None
    requested_metrics = requested_metrics or []
    visible_keys = tuple(
        key
        for key, _label in CHART_METRIC_CHOICES
        if key in requested_metrics
    )
    if not visible_keys:
        visible_keys = tuple(key for key, _label in CHART_METRIC_CHOICES)
    layout = requested_layout if requested_layout in CHART_LAYOUT_KEYS else "combined"
    if not comparison_series:
        layout = "combined"
    values_for_scale = [value for key in visible_keys for value in series[key]]
    if comparison_series:
        values_for_scale += [
            value
            for key in visible_keys
            for value in comparison_series[key]
        ]
    data_maximum = max(values_for_scale, default=0) or 1
    if data_maximum <= 5:
        axis_step = 1
    else:
        rough_step = data_maximum / 5
        magnitude = 10 ** floor(log10(rough_step))
        normalized_step = rough_step / magnitude
        if normalized_step <= 1:
            axis_step = magnitude
        elif normalized_step <= 2:
            axis_step = 2 * magnitude
        elif normalized_step <= 5:
            axis_step = 5 * magnitude
        else:
            axis_step = 10 * magnitude
    maximum = max(axis_step, ceil(data_maximum / axis_step) * axis_step)
    points = []
    point_count = max(
        len(series["labels"]),
        len(comparison_series["labels"]) if comparison_series else 0,
    )
    for index in range(point_count):
        label = series["labels"][index] if index < len(series["labels"]) else "—"
        values = {
            key: series[key][index] if index < len(series[key]) else 0
            for key in ("incoming", "done", "rejected")
        }
        comparison_values = {
            key: comparison_series[key][index]
            if comparison_series and index < len(comparison_series[key])
            else 0
            for key in ("incoming", "done", "rejected")
        }
        points.append(
            {
                "label": label,
                "comparison_label": (
                    comparison_series["labels"][index]
                    if comparison_series and index < len(comparison_series["labels"])
                    else ""
                ),
                **values,
                **{
                    f"{key}_percent": max(round(value * 100 / maximum), 2) if value else 0
                    for key, value in values.items()
                },
                **{f"comparison_{key}": value for key, value in comparison_values.items()},
                **{
                    f"comparison_{key}_percent": max(round(value * 100 / maximum), 2)
                    if value
                    else 0
                    for key, value in comparison_values.items()
                },
            }
        )

    chart_left = 174
    chart_right = 976
    chart_top = 16
    chart_bottom = 214

    def line_points(field_name):
        coordinates = []
        for index, point in enumerate(points):
            if len(points) == 1:
                x = (chart_left + chart_right) / 2
            else:
                x = chart_left + index * (chart_right - chart_left) / (len(points) - 1)
            y = chart_bottom - point[field_name] * (chart_bottom - chart_top) / maximum
            coordinates.append(f"{x:.1f},{y:.1f}")
        return " ".join(coordinates)

    tick_count = min(len(points), 7)
    if tick_count <= 1:
        tick_indexes = [0] if points else []
    else:
        tick_indexes = sorted(
            {
                round(index * (len(points) - 1) / (tick_count - 1))
                for index in range(tick_count)
            }
        )
    ticks = []
    for index in tick_indexes:
        x = (
            (chart_left + chart_right) / 2
            if len(points) == 1
            else chart_left + index * (chart_right - chart_left) / (len(points) - 1)
        )
        ticks.append(
            {
                "x": f"{x:.1f}",
                "label": points[index]["label"],
                "comparison_label": points[index]["comparison_label"],
            }
        )

    lines = {
        key: {
            "current": line_points(key),
            "comparison": line_points(f"comparison_{key}") if comparison_series else "",
        }
        for key in visible_keys
    }
    line_labels = []
    line_definitions = (
        ("incoming", "Поступило", "circle"),
        ("done", "Исполнено", "square"),
        ("rejected", "Отклонено", "triangle"),
    )
    for key, label, marker in line_definitions:
        if key not in visible_keys:
            continue
        line_labels.append(
            {
                "key": key,
                "label": f"{label}, основной",
                "marker": marker,
                "comparison": False,
                "point_y": chart_bottom - points[0][key] * (chart_bottom - chart_top) / maximum,
            }
        )
        if comparison_series:
            line_labels.append(
                {
                    "key": key,
                    "label": f"{label}, сравнение",
                    "marker": marker,
                    "comparison": True,
                    "point_y": chart_bottom
                    - points[0][f"comparison_{key}"] * (chart_bottom - chart_top) / maximum,
                }
            )
    line_labels.sort(key=lambda item: item["point_y"])
    label_gap = 13
    for index, item in enumerate(line_labels):
        item["label_y"] = max(
            item["point_y"],
            chart_top if index == 0 else line_labels[index - 1]["label_y"] + label_gap,
        )
    if line_labels and line_labels[-1]["label_y"] > chart_bottom:
        overflow = line_labels[-1]["label_y"] - chart_bottom
        for item in line_labels:
            item["label_y"] -= overflow
    for item in line_labels:
        item["point_y"] = f"{item['point_y']:.1f}"
        item["label_y"] = f"{item['label_y']:.1f}"
    y_ticks = []
    tick_value = 0
    while tick_value <= maximum:
        y = chart_bottom - tick_value * (chart_bottom - chart_top) / maximum
        y_ticks.append(
            {
                "y": f"{y:.1f}",
                "label": str(int(tick_value) if float(tick_value).is_integer() else tick_value),
            }
        )
        tick_value += axis_step

    def build_separate_panel(panel_series, title):
        panel_top = 10
        panel_bottom = 116
        panel_points = [
            {
                "label": label,
                **{key: panel_series[key][index] for key in visible_keys},
            }
            for index, label in enumerate(panel_series["labels"])
        ]

        def panel_line_points(field_name):
            coordinates = []
            for index, point in enumerate(panel_points):
                x = (
                    (chart_left + chart_right) / 2
                    if len(panel_points) == 1
                    else chart_left
                    + index * (chart_right - chart_left) / (len(panel_points) - 1)
                )
                y = panel_bottom - point[field_name] * (panel_bottom - panel_top) / maximum
                coordinates.append(f"{x:.1f},{y:.1f}")
            return " ".join(coordinates)

        panel_tick_count = min(len(panel_points), 7)
        if panel_tick_count <= 1:
            panel_tick_indexes = [0] if panel_points else []
        else:
            panel_tick_indexes = sorted(
                {
                    round(index * (len(panel_points) - 1) / (panel_tick_count - 1))
                    for index in range(panel_tick_count)
                }
            )
        panel_ticks = []
        for index in panel_tick_indexes:
            x = (
                (chart_left + chart_right) / 2
                if len(panel_points) == 1
                else chart_left
                + index * (chart_right - chart_left) / (len(panel_points) - 1)
            )
            panel_ticks.append({"x": f"{x:.1f}", "label": panel_points[index]["label"]})

        panel_labels = []
        for key, label, marker in line_definitions:
            if key not in visible_keys:
                continue
            point_y = panel_bottom - panel_points[0][key] * (panel_bottom - panel_top) / maximum
            panel_labels.append(
                {
                    "key": key,
                    "label": label,
                    "marker": marker,
                    "point_y_value": point_y,
                }
            )
        panel_labels.sort(key=lambda item: item["point_y_value"])
        for index, item in enumerate(panel_labels):
            item["label_y_value"] = max(
                item["point_y_value"],
                panel_top if index == 0 else panel_labels[index - 1]["label_y_value"] + 12,
            )
        if panel_labels and panel_labels[-1]["label_y_value"] > panel_bottom:
            overflow = panel_labels[-1]["label_y_value"] - panel_bottom
            for item in panel_labels:
                item["label_y_value"] -= overflow
        for item in panel_labels:
            item["point_y"] = f"{item.pop('point_y_value'):.1f}"
            item["label_y"] = f"{item.pop('label_y_value'):.1f}"

        panel_y_ticks = []
        panel_tick_value = 0
        while panel_tick_value <= maximum:
            y = panel_bottom - panel_tick_value * (panel_bottom - panel_top) / maximum
            panel_y_ticks.append(
                {
                    "y": f"{y:.1f}",
                    "label": str(
                        int(panel_tick_value)
                        if float(panel_tick_value).is_integer()
                        else panel_tick_value
                    ),
                }
            )
            panel_tick_value += axis_step
        return {
            "title": title,
            "bottom": panel_bottom,
            "tick_bottom": panel_bottom + 5,
            "tick_label_y": panel_bottom + 19,
            "lines": {key: panel_line_points(key) for key in visible_keys},
            "ticks": panel_ticks,
            "y_ticks": list(reversed(panel_y_ticks)),
            "line_labels": panel_labels,
        }

    panels = [build_separate_panel(series, current_period_label)]
    if comparison_series:
        panels.append(build_separate_panel(comparison_series, comparison_period_label))
    return {
        "granularity": granularity,
        "granularity_label": GRANULARITY_LABELS[granularity],
        "has_comparison": comparison_series is not None,
        "selected_metrics": visible_keys,
        "layout": layout,
        "metric_label": (
            "Все показатели"
            if len(visible_keys) == len(CHART_METRIC_CHOICES)
            else ", ".join(dict(CHART_METRIC_CHOICES)[key] for key in visible_keys)
        ),
        "show_incoming": "incoming" in visible_keys,
        "show_done": "done" in visible_keys,
        "show_rejected": "rejected" in visible_keys,
        "points": points,
        "lines": lines,
        "line_labels": line_labels,
        "ticks": ticks,
        "y_ticks": list(reversed(y_ticks)),
        "maximum": maximum,
        "plot_left": chart_left,
        "panels": panels,
    }


def selected_organs_label(organs, available_organs):
    if not organs:
        return "Территориальные органы не выбраны"
    if len(organs) == len(available_organs):
        return f"Все доступные территориальные органы ({len(organs)})"
    names = [organ.name for organ in organs]
    if len(names) <= 4:
        return "; ".join(names)
    return f"{'; '.join(names[:4])}; ещё {len(names) - 4}"


def selected_departments_label(departments, available_departments):
    if not departments:
        return "Отделы не выбраны"
    if len(departments) == len(available_departments):
        return f"Все отделы ({len(departments)})"
    names = [department.name for department in departments]
    if len(names) <= 4:
        return "; ".join(names)
    return f"{'; '.join(names[:4])}; ещё {len(names) - 4}"


def report_filter_fields(request):
    allowed = {
        "period",
        "date_from",
        "date_to",
        "organ_ids",
        "organ_filter_empty",
        "department_ids",
        "department_filter_empty",
        "granularity",
    }
    return [
        (key, value)
        for key, values in request.GET.lists()
        if key in allowed
        for value in values
    ]


def build_summary_report_context(request):
    period = parse_period(request)
    comparison_mode = request.GET.get("comparison", "none")
    if comparison_mode not in COMPARISON_KEYS:
        comparison_mode = "none"
    default_custom_period = previous_comparison_period(period)
    custom_date_from = parse_date(request.GET.get("comparison_date_from", ""))
    custom_date_to = parse_date(request.GET.get("comparison_date_to", ""))
    if default_custom_period:
        custom_date_from = custom_date_from or default_custom_period["date_from"]
        custom_date_to = custom_date_to or default_custom_period["date_to"]
    compared_period = comparison_period(
        period,
        comparison_mode,
        custom_date_from=custom_date_from,
        custom_date_to=custom_date_to,
    )
    if comparison_mode == "custom" and compared_period:
        custom_date_from = compared_period["date_from"]
        custom_date_to = compared_period["date_to"]
    if period["period"] == "all":
        comparison_mode = "none"

    available_organs = available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    tables = list(request_tables())
    available_departments_list = available_departments(tables)
    departments = selected_departments(request, available_departments_list)
    department_slugs = {department.slug for department in departments}
    tables = [table for table in tables if table["department"] in department_slugs]
    history_flags = status_history_flags(tables, organs)
    current_base_metrics = table_base_metrics(tables, organs, period)
    current_kpi = build_kpi(tables, organs, period, history_flags, current_base_metrics)
    comparison_kpi = None
    if compared_period:
        comparison_base_metrics = table_base_metrics(tables, organs, compared_period)
        comparison_kpi = build_kpi(tables, organs, compared_period, history_flags, comparison_base_metrics)

    dynamics = build_dynamics(tables, organs, period, history_flags)
    comparison_dynamics = None
    if compared_period:
        comparison_dynamics = build_dynamics(tables, organs, compared_period, history_flags)
    requested_metrics = request.GET.getlist("metrics")
    if not requested_metrics and request.GET.get("metric") in CHART_METRIC_KEYS:
        requested_metrics = [request.GET["metric"]]
    selected_metrics = [
        key for key, _label in CHART_METRIC_CHOICES if key in requested_metrics
    ] or [key for key, _label in CHART_METRIC_CHOICES]
    chart = report_chart(
        dynamics,
        request.GET.get("granularity", ""),
        comparison_dynamics=comparison_dynamics,
        requested_metrics=selected_metrics,
        requested_layout=request.GET.get("chart_layout", "combined"),
        current_period_label=period["label"],
        comparison_period_label=compared_period["label"] if compared_period else "",
    )
    problem_organs = [
        row
        for row in build_org_chart(
            tables,
            organs,
            period,
            metric="stale",
            history_flags=history_flags,
        )
        if row["value"]
    ][:5]
    department_load = [
        row
        for row in build_department_load(tables, organs, current_base_metrics)
        if row["value"]
    ][:6]
    comparison_label = dict(COMPARISON_CHOICES)[comparison_mode]
    if compared_period:
        comparison_label = f"{comparison_label}: {compared_period['label']}"

    period_days = (
        (period["date_to"] - period["date_from"]).days + 1
        if period.get("date_from") and period.get("date_to")
        else None
    )
    comparison_days = (
        (compared_period["date_to"] - compared_period["date_from"]).days + 1
        if compared_period
        else None
    )
    different_period_lengths = bool(
        period_days
        and comparison_days
        and period_days != comparison_days
        and not (
            _is_full_month(period["date_from"], period["date_to"])
            and _is_full_month(compared_period["date_from"], compared_period["date_to"])
        )
        and not (
            _is_full_year(period["date_from"], period["date_to"])
            and _is_full_year(compared_period["date_from"], compared_period["date_to"])
        )
        and abs(period_days - comparison_days) > 1
    )

    return {
        "period": serialize_period(period),
        "comparison_mode": comparison_mode,
        "comparison_choices": COMPARISON_CHOICES,
        "comparison_period": serialize_period(compared_period) if compared_period else None,
        "comparison_label": comparison_label,
        "metric_rows": report_metric_rows(
            current_kpi,
            comparison_kpi,
            current_days=period_days,
            comparison_days=comparison_days,
            show_daily_average=different_period_lengths,
        ),
        "period_days": period_days,
        "comparison_days": comparison_days,
        "different_period_lengths": different_period_lengths,
        "comparison_date_from": custom_date_from.isoformat() if custom_date_from else "",
        "comparison_date_to": custom_date_to.isoformat() if custom_date_to else "",
        "chart": chart,
        "chart_metric_choices": CHART_METRIC_CHOICES,
        "chart_layout_choices": CHART_LAYOUT_CHOICES,
        "chart_metric_label": (
            "Все показатели"
            if len(selected_metrics) == len(CHART_METRIC_CHOICES)
            else ", ".join(dict(CHART_METRIC_CHOICES)[key] for key in selected_metrics)
        ),
        "problem_organs": problem_organs,
        "department_load": department_load,
        "attention_requests": build_attention_requests(tables, organs, limit=10),
        "selected_organs_label": selected_organs_label(organs, available_organs),
        "selected_organs_count": len(organs),
        "selected_departments_label": selected_departments_label(departments, available_departments_list),
        "selected_departments_count": len(departments),
        "generated_at": timezone.localtime(),
        "report_filter_fields": report_filter_fields(request),
        "dashboard_url": reverse("admin_panel"),
        "report_url": reverse("admin_summary_report"),
    }
