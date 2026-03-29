"""
airflow/dags/daily_parsers_dag.py
DAG запускает 5 парсеров локально внутри Airflow-контейнера через BashOperator.
Пакеты для парсеров установлены прямо в Airflow через _PIP_ADDITIONAL_REQUIREMENTS в .env.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = "/opt/airflow/project"

default_args = {
    "owner": "automarket",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
    "execution_timeout": timedelta(hours=5),
}

with DAG(
    dag_id="daily_car_parsers",
    default_args=default_args,
    description="Ежедневный сбор данных с 5 площадок авторынка KZ",
    schedule="0 3 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["parsers", "automarket"],
) as dag:

    # ─── Шаг 1: обновляем прокси-пул ─────────────────────────────────────
    refresh_proxies = BashOperator(
        task_id="refresh_proxy_pool",
        bash_command=(
            f"cd {PROJECT_DIR} && "
            "python -c "
            "'import asyncio; from parsers.common.proxy_manager import proxy_manager; "
            "asyncio.run(proxy_manager.refresh()); "
            "print(\"Прокси обновлены: \" + str(len(proxy_manager._working_proxies)))' "
            "|| echo 'Прокси недоступны, продолжаем без них'"
        ),
    )

    # ─── Шаг 2: все 5 парсеров параллельно ───────────────────────────────
    sites = ["kolesa", "avtorynok", "mycar", "newauto", "olx"]
    parser_tasks = []
    
    for site in sites:
        task = BashOperator(
            task_id=f"parse_{site}",
            bash_command=f"cd {PROJECT_DIR} && python -m parsers.{site}.parser",
            trigger_rule="all_done",
        )
        parser_tasks.append(task)

    # ─── Шаг 3: Деактивация старых объявлений ──────────────────────────────
    deactivate_task = BashOperator(
        task_id="deactivate_old_listings",
        bash_command=f"cd {PROJECT_DIR} && python -m parsers.common.deactivate",
        trigger_rule="all_done",
    )

    # refresh_proxies → [все парсеры параллельно] → [деактивация]
    refresh_proxies >> parser_tasks >> deactivate_task
