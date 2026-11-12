#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D2PFX Launcher — десктоп-лаунчер для каталога модов https://h6rd.github.io/Dota2PornFxWeb/

Что умеет:
  * загружает с сайта все категории и все моды (название, превью, ссылка);
  * находит файлы модов в репозитории h6rd/Dota2PornFxWeb (GitHub / jsDelivr);
  * скачивает моды, кэширует их, собирает все выбранные моды в один pak01_dir.vpk
    и кладёт его в  <Dota 2>/game/<языковая папка>/pak01_dir.vpk ;
  * удаляет моды и откатывает установку (делает бэкап чужого pak01_dir.vpk).

Зависимости: только стандартная библиотека Python 3.8+.
Опционально: `pip install pillow` — чтобы показывались превью (.webp).

Запуск:  python launcher.py
"""

import io
import json
import os
import queue
import re
import shutil
import struct
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:  # pragma: no cover
    tk = None

Image = ImageTk = None
HAS_PIL = False


def load_pillow():
    """Пробует импортировать Pillow (нужен для превью .webp)."""
    global Image, ImageTk, HAS_PIL
    try:
        import importlib
        importlib.invalidate_caches()
        from PIL import Image as _I, ImageTk as _IT  # type: ignore
        Image, ImageTk, HAS_PIL = _I, _IT, True
    except Exception:
        HAS_PIL = False
    return HAS_PIL


def install_pillow():
    """Ставит Pillow в ТОТ ЖЕ Python, которым запущен лаунчер."""
    import subprocess
    if getattr(sys, "frozen", False):
        return False, "frozen exe"
    flags = 0x08000000 if sys.platform.startswith("win") else 0  # без чёрного окна консоли
    for extra in ([], ["--user"]):
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pillow", *extra],
                           capture_output=True, text=True, creationflags=flags)
        if r.returncode == 0 and load_pillow():
            return True, ""
    lines = (r.stderr or r.stdout or "").strip().splitlines()
    return False, lines[-1] if lines else "pip error"


load_pillow()

# ----------------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------------
SITE = "https://h6rd.github.io/Dota2PornFxWeb/"
OWNER, REPO = "h6rd", "Dota2PornFxWeb"
BRANCHES = ["mirror", "main", "master", "gh-pages"]
UA = "Mozilla/5.0 (D2PFX-Launcher; +https://github.com/h6rd/Dota2PornFxWeb)"

MOD_EXTS = (".vpk", ".zip", ".7z", ".rar")
IMG_EXTS = (".webp", ".png", ".jpg", ".jpeg", ".gif", ".bmp")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".gifv")
GAME_TOP_DIRS = ("materials", "particles", "sounds", "soundevents", "models",
                 "panorama", "resource", "scripts", "maps", "cfg", "media")

FALLBACK_CATEGORIES = [
    ("shaders", "Shaders"), ("ti-bp-effects", "Effect Packs"), ("heroes", "Heroes"),
    ("terrains", "Terrains"), ("trees", "Trees"), ("creeps", "Creeps"),
    ("creep-deny", "Creep Deny"), ("emblems", "Emblems"), ("backgrounds", "Backgrounds"),
    ("hero-items", "Hero Items"), ("herofx", "Hero Spells"), ("hero-sounds", "Hero Sounds"),
    ("sounds", "Sounds"), ("wards", "Wards"), ("couriers", "Couriers"), ("river", "River"),
    ("item-effects", "Item Effects"), ("ranged-attack", "Ranged Attack"), ("pings", "Pings"),
    ("parts", "Parts"), ("huds", "Huds"), ("packs", "Packs"),
    ("versus-screens", "Versus Screens"), ("mega-kill", "Mega-Kill"),
    ("announcers", "Announcers"), ("music", "Music"), ("roshan", "Roshan"),
    ("ancient", "Ancient"), ("tormentor", "Tormentor"), ("towers", "Towers"),
    ("pedestal", "Pedestal"), ("high-five", "High Five"), ("item-icons", "Item Icons"),
    ("hero-icons", "Hero Icons"), ("ranks", "Rank Icons"), ("cursors", "Cursors"),
    ("fonts", "Fonts"), ("other", "Other"), ("optimization", "Optimization"),
]
NON_MOD_CATEGORIES = {"tools", "guides", "sites"}

LANG_FOLDERS = ["dota_english", "dota_russian", "dota_schinese", "dota_tchinese",
                "dota_spanish", "dota_latam", "dota_brazilian", "dota_portuguese",
                "dota_german", "dota_french", "dota_italian", "dota_polish",
                "dota_ukrainian", "dota_korean", "dota_japanese", "dota_turkish",
                "dota_czech", "dota_thai", "dota_vietnamese", "dota_tempcontent"]

GUIDE_STEPS = {
    "ru": [
        ("Настройки", "Нажмите «⚙ Настройки» → «Найти» (или «Обзор…» и выберите папку dota 2 beta). "
                      "Папку языка игры можно оставить dota_english."),
        ("Выберите моды", "Слева выберите категорию или ищите сверху. Нажмите на карточку, чтобы посмотреть мод."),
        ("Установите", "Нажмите ＋ на карточке или «＋ Установить» справа — мод скачается и появится в «Мои моды»."),
        ("Порядок", "Если два мода меняют одно и то же — сработает тот, что выше в списке. Двигайте стрелками ↑↓."),
        ("Примените", "Нажмите красную кнопку «✔ Применить в Dota» — лаунчер соберёт все моды в игру."),
        ("Параметр запуска (один раз)", "Steam → Dota 2 → ПКМ → Свойства → Параметры запуска: впишите  {o}"),
        ("Играйте", "Нажмите «▶ Запустить Dota 2». После обновления Dota, если моды пропали, просто нажмите «Применить» снова."),
    ],
    "en": [
        ("Settings", "Click “⚙ Settings” → “Detect” (or “Browse…” and pick the dota 2 beta folder). "
                     "You can leave the game language folder as dota_english."),
        ("Pick mods", "Choose a category on the left or search at the top. Click a card to see the mod."),
        ("Install", "Click ＋ on a card or “＋ Install” on the right — the mod downloads and appears in “My mods”."),
        ("Order", "If two mods change the same thing, the higher one wins. Move them with ↑↓."),
        ("Apply", "Click the red “✔ Apply to Dota” button — the launcher builds all mods into the game."),
        ("Launch option (once)", "Steam → Dota 2 → right-click → Properties → Launch options: type  {o}"),
        ("Play", "Click “▶ Launch Dota 2”. If mods disappear after a Dota update, just press “Apply” again."),
    ],
    "uk": [
        ("Налаштування", "Натисніть «⚙ Налаштування» → «Знайти» (або «Огляд…» і виберіть теку dota 2 beta). "
                         "Теку мови гри можна залишити dota_english."),
        ("Оберіть моди", "Ліворуч виберіть категорію або шукайте вгорі. Натисніть на картку, щоб переглянути мод."),
        ("Встановіть", "Натисніть ＋ на картці або «＋ Встановити» праворуч — мод завантажиться й з'явиться в «Мої моди»."),
        ("Порядок", "Якщо два моди змінюють одне й те саме — спрацює той, що вище. Пересувайте стрілками ↑↓."),
        ("Застосуйте", "Натисніть червону кнопку «✔ Застосувати в Dota» — лаунчер збере всі моди в гру."),
        ("Параметр запуску (один раз)", "Steam → Dota 2 → ПКМ → Властивості → Параметри запуску: впишіть  {o}"),
        ("Грайте", "Натисніть «▶ Запустити Dota 2». Якщо після оновлення Dota моди зникли — знову натисніть «Застосувати»."),
    ],
}

# Тёмная тема (в стиле Dota 2)
C = {
    "bg": "#121419", "panel": "#1a1d24", "card": "#22262f", "hover": "#2c313c", "field": "#0e1014",
    "border": "#2e333d", "text": "#e8e9ec", "muted": "#8b93a1", "accent": "#c8372d", "accent_h": "#e0483d",
    "ok": "#5fd068", "thumb": "#2a2f39",
}
FONT = "Segoe UI" if sys.platform.startswith("win") else ("Helvetica Neue" if sys.platform == "darwin" else "DejaVu Sans")
THUMB_W, THUMB_H = 220, 124
CARD_W = THUMB_W + 4
PAGE_SIZE = 60

APP_DIR = Path.home() / ".d2pfx_launcher"
CACHE_DIR = APP_DIR / "cache"
DL_DIR = APP_DIR / "mods"
CONFIG_FILE = APP_DIR / "config.json"
MARKER_NAME = ".d2pfx_launcher.json"


# ----------------------------------------------------------------------------
# Локализация интерфейса
# ----------------------------------------------------------------------------
UI_LANGS = {"ru": "Русский", "en": "English", "uk": "Українська"}
_LANG = "ru"

STRINGS = {
    "title": ("D2PFX Launcher — моды Dota 2", "D2PFX Launcher — Dota 2 mods", "D2PFX Launcher — моди Dota 2"),
    "dota": ("Dota 2:", "Dota 2:", "Dota 2:"),
    "browse": ("Обзор…", "Browse…", "Огляд…"),
    "lang_folder": ("  Папка языка игры:", "  Game language folder:", "  Тека мови гри:"),
    "ui_lang": ("Язык:", "Language:", "Мова:"),
    "apply": ("✔ Применить в Dota", "✔ Apply to Dota", "✔ Застосувати в Dota"),
    "run": ("Запустить Dota 2", "Launch Dota 2", "Запустити Dota 2"),
    "categories": ("Категории", "Categories", "Категорії"),
    "search": ("Поиск:", "Search:", "Пошук:"),
    "all_cats": ("во всех категориях", "in all categories", "в усіх категоріях"),
    "col_mod": ("Мод", "Mod", "Мод"),
    "col_cat": ("Категория", "Category", "Категорія"),
    "col_state": ("Статус", "Status", "Статус"),
    "installed_mark": ("✔ установлен", "✔ installed", "✔ встановлено"),
    "count": ("Модов: {n}", "Mods: {n}", "Модів: {n}"),
    "show_more": ("Показать ещё ({n})", "Show more ({n})", "Показати ще ({n})"),
    "pil_installing": ("Нет Pillow для превью — устанавливаю в {py} …", "Pillow missing for previews — installing into {py} …",
                       "Немає Pillow для прев'ю — встановлюю в {py} …"),
    "pil_ok": ("Pillow установлен, загружаю превью.", "Pillow installed, loading previews.", "Pillow встановлено, завантажую прев'ю."),
    "pil_fail": ("Не удалось установить Pillow ({e}). Выполните вручную:  \"{py}\" -m pip install pillow",
                 "Could not install Pillow ({e}). Run manually:  \"{py}\" -m pip install pillow",
                 "Не вдалося встановити Pillow ({e}). Виконайте вручну:  \"{py}\" -m pip install pillow"),
    "subtitle": ("лаунчер модов Dota 2", "Dota 2 mod launcher", "лаунчер модів Dota 2"),
    "settings": ("Настройки", "Settings", "Налаштування"),
    "hint_dbl": ("двойной клик или ＋ — установить", "double-click or ＋ to install", "подвійний клік або ＋ — встановити"),
    "loading": ("Загрузка…", "Loading…", "Завантаження…"),
    "ready": ("Готово к работе", "Ready", "Готово до роботи"),
    "log_show": ("Журнал ▴", "Log ▴", "Журнал ▴"),
    "log_hide": ("Журнал ▾", "Log ▾", "Журнал ▾"),
    "pick_mod_hint": ("Нажмите на мод,\nчтобы увидеть подробности", "Click a mod\nto see details",
                      "Натисніть на мод,\nщоб побачити подробиці"),
    "my_mods": ("Мои моды ({n})", "My mods ({n})", "Мої моди ({n})"),
    "prio_hint": ("Верхний мод важнее, если моды пересекаются", "Top mod wins if mods overlap",
                  "Верхній мод важливіший, якщо моди перетинаються"),
    "search_ph": ("Поиск модов…", "Search mods…", "Пошук модів…"),
    "auto_detect": ("Найти", "Detect", "Знайти"),
    "not_detected": ("Dota 2 не найдена автоматически — укажите папку вручную.",
                     "Dota 2 not found automatically — choose the folder manually.",
                     "Dota 2 не знайдено автоматично — вкажіть теку вручну."),
    "path_ok": ("✔ Папка Dota 2 найдена", "✔ Dota 2 folder found", "✔ Теку Dota 2 знайдено"),
    "path_bad": ("✕ Это не папка «dota 2 beta»", "✕ This is not the “dota 2 beta” folder", "✕ Це не тека «dota 2 beta»"),
    "launch_hint": ("Параметр запуска Steam для этой папки:  {o}", "Steam launch option for this folder:  {o}",
                    "Параметр запуску Steam для цієї теки:  {o}"),
    "save": ("Сохранить", "Save", "Зберегти"),
    "cancel": ("Отмена", "Cancel", "Скасувати"),
    "close": ("Закрыть", "Close", "Закрити"),
    "all_mods": ("Все моды", "All mods", "Усі моди"),
    "nothing_found": ("Ничего не найдено", "Nothing found", "Нічого не знайдено"),
    "done_short": ("Моды собраны в игру: {n} файлов.", "Mods built into the game: {n} files.", "Моди зібрано в гру: {n} файлів."),
    "launch_step": ("Один раз добавьте в Steam → Dota 2 → Свойства → Параметры запуска:",
                    "Once, add to Steam → Dota 2 → Properties → Launch options:",
                    "Один раз додайте в Steam → Dota 2 → Властивості → Параметри запуску:"),
    "copy": ("Копировать", "Copy", "Копіювати"),
    "copied": ("Скопировано", "Copied", "Скопійовано"),
    "guide": ("Гайд", "Guide", "Гайд"),
    "guide_title": ("Как пользоваться", "How to use", "Як користуватися"),
    "guide_sub": ("7 шагов — и моды в игре", "7 steps and the mods are in the game", "7 кроків — і моди в грі"),
    "guide_ok": ("Понятно, начать", "Got it, let's start", "Зрозуміло, почати"),
    "guide_remove_h": ("Как убрать моды", "How to remove mods", "Як прибрати моди"),
    "guide_remove": ("Один мод: удалите его из «Мои моды» и нажмите «Применить».\n"
                     "Все сразу: кнопка «⌫ Удалить моды из Dota» — игра станет чистой, а ваш список модов сохранится. "
                     "Параметр -language из Steam можно убрать.",
                     "One mod: remove it from “My mods” and press “Apply”.\n"
                     "All at once: the “⌫ Remove mods from Dota” button — the game becomes clean, your mod list is kept. "
                     "You can remove the -language option in Steam.",
                     "Один мод: видаліть його з «Мої моди» і натисніть «Застосувати».\n"
                     "Усі одразу: кнопка «⌫ Видалити моди з Dota» — гра стане чистою, а ваш список модів збережеться. "
                     "Параметр -language у Steam можна прибрати."),
    "uninstall_game": ("Удалить моды из Dota", "Remove mods from Dota", "Видалити моди з Dota"),
    "uninstall_confirm": ("Удалить все установленные лаунчером моды из файлов Dota 2?\n\nСписок «Мои моды» сохранится — их можно вернуть кнопкой «Применить».",
                          "Remove all launcher-installed mods from Dota 2 files?\n\nYour “My mods” list is kept — press “Apply” to bring them back.",
                          "Видалити всі встановлені лаунчером моди з файлів Dota 2?\n\nСписок «Мої моди» збережеться — їх можна повернути кнопкою «Застосувати»."),
    "uninstall_done": ("Моды удалены из игры (папки: {f}). Dota 2 теперь без модов.",
                       "Mods removed from the game (folders: {f}). Dota 2 is now clean.",
                       "Моди видалено з гри (теки: {f}). Dota 2 тепер без модів."),
    "uninstall_none": ("В файлах Dota 2 нет модов, установленных лаунчером.", "No launcher-installed mods found in Dota 2 files.",
                       "У файлах Dota 2 немає модів, встановлених лаунчером."),
    "removed_from": ("Удалён pak01_dir.vpk из game/{f}", "Removed pak01_dir.vpk from game/{f}", "Видалено pak01_dir.vpk з game/{f}"),
    "preview_fail": ("Превью «{m}» не загрузилось: {e}", "Preview of “{m}” failed: {e}", "Прев'ю «{m}» не завантажилось: {e}"),
    "video_preview": ("▶ видео-превью\n(откройте на сайте)", "▶ video preview\n(open on site)", "▶ відео-прев'ю\n(відкрийте на сайті)"),
    "pick_mod": ("Выберите мод", "Select a mod", "Оберіть мод"),
    "need_pil": ("Загрузка превью…", "Loading preview…", "Завантаження прев'ю…"),
    "no_preview": ("(превью недоступно)", "(preview unavailable)", "(прев'ю недоступне)"),
    "install": ("Установить", "Install", "Встановити"),
    "remove": ("Удалить", "Remove", "Видалити"),
    "remove_all": ("Удалить все", "Remove all", "Видалити всі"),
    "open_site": ("Открыть на сайте", "Open on site", "Відкрити на сайті"),
    "own_file": ("Свой файл…", "Own file…", "Свій файл…"),
    "installed_list": ("Установленные моды (порядок = приоритет):", "Installed mods (order = priority):",
                       "Встановлені моди (порядок = пріоритет):"),
    "info_cat": ("Категория: {c}", "Category: {c}", "Категорія: {c}"),
    "info_file": ("Файл: {p}", "File: {p}", "Файл: {p}"),
    "mb": (" ({n:.1f} МБ)", " ({n:.1f} MB)", " ({n:.1f} МБ)"),
    "file_not_found": ("Файл в репозитории не найден — используйте «Открыть на сайте» и «Свой файл…»",
                       "File not found in repository — use “Open on site” and “Own file…”",
                       "Файл у репозиторії не знайдено — скористайтеся «Відкрити на сайті» і «Свій файл…»"),
    "index_building": ("Индекс файлов ещё строится…", "File index is still being built…", "Індекс файлів ще будується…"),
    "err": ("Ошибка: {e}", "Error: {e}", "Помилка: {e}"),
    "error_title": ("Ошибка", "Error", "Помилка"),
    "loading_cats": ("Загружаю категории с сайта…", "Loading categories from the site…", "Завантажую категорії з сайту…"),
    "cats_loaded": ("Категорий: {n}. Индексирую файлы модов…", "Categories: {n}. Indexing mod files…",
                    "Категорій: {n}. Індексую файли модів…"),
    "cat_mods": ("{s}: {n} модов", "{s}: {n} mods", "{s}: {n} модів"),
    "cat_fail": ("{s}: не удалось загрузить ({e})", "{s}: failed to load ({e})", "{s}: не вдалося завантажити ({e})"),
    "home_fail": ("Не удалось прочитать главную страницу: {e}", "Could not read the main page: {e}",
                  "Не вдалося прочитати головну сторінку: {e}"),
    "index_found": ("Найдено файлов модов в репозитории: {n}", "Mod files found in repository: {n}",
                    "Знайдено файлів модів у репозиторії: {n}"),
    "tree_trunc": ("[{b}] дерево GitHub обрезано, дополняю через jsDelivr", "[{b}] GitHub tree truncated, using jsDelivr",
                   "[{b}] дерево GitHub обрізане, доповнюю через jsDelivr"),
    "wait_index": ("Подождите, индекс файлов ещё строится…", "Please wait, the file index is still being built…",
                   "Зачекайте, індекс файлів ще будується…"),
    "no_file": ("Не нашёл файл для «{m}». Скачайте его на сайте и нажмите «Свой файл…».",
                "No file found for “{m}”. Download it on the site and press “Own file…”.",
                "Не знайшов файл для «{m}». Завантажте його на сайті й натисніть «Свій файл…»."),
    "downloading": ("Скачиваю {m}…", "Downloading {m}…", "Завантажую {m}…"),
    "dl_fail": ("Не удалось скачать «{m}»: {e}", "Failed to download “{m}”: {e}", "Не вдалося завантажити «{m}»: {e}"),
    "added": ("Добавлен: {m} ({n} файлов). Нажмите «Применить моды в Dota».",
              "Added: {m} ({n} files). Press “Apply mods to Dota”.",
              "Додано: {m} ({n} файлів). Натисніть «Застосувати моди в Dota»."),
    "removed": ("Удалён: {m}", "Removed: {m}", "Видалено: {m}"),
    "mod_file": ("Файл мода", "Mod file", "Файл моду"),
    "ft_mods": ("Моды", "Mods", "Моди"),
    "ft_all": ("Все", "All", "Усі"),
    "confirm_all": ("Убрать все моды? (затем нажмите «Применить»)", "Remove all mods? (then press “Apply”)",
                    "Прибрати всі моди? (потім натисніть «Застосувати»)"),
    "cleared": ("Список модов очищен.", "Mod list cleared.", "Список модів очищено."),
    "dota_dir": ("Папка Dota 2 (dota 2 beta)", "Dota 2 folder (dota 2 beta)", "Тека Dota 2 (dota 2 beta)"),
    "building": ("Собираю pak01_dir.vpk…", "Building pak01_dir.vpk…", "Збираю pak01_dir.vpk…"),
    "install_err": ("Ошибка установки: {e}", "Install error: {e}", "Помилка встановлення: {e}"),
    "conflict": ("  конфликт: {k} — «{b}» перекрыл «{a}»", "  conflict: {k} — “{b}” overrides “{a}”",
                 "  конфлікт: {k} — «{b}» перекрив «{a}»"),
    "done": ("Готово: {n} файлов в game/{f}/pak01_dir.vpk\n\nВ Steam → Dota 2 → Свойства → Параметры запуска добавьте:\n{o}",
             "Done: {n} files in game/{f}/pak01_dir.vpk\n\nIn Steam → Dota 2 → Properties → Launch options add:\n{o}",
             "Готово: {n} файлів у game/{f}/pak01_dir.vpk\n\nУ Steam → Dota 2 → Властивості → Параметри запуску додайте:\n{o}"),
    "done_title": ("Моды установлены", "Mods installed", "Моди встановлено"),
    "no_dota": ("Не указана папка Dota 2 (…/steamapps/common/dota 2 beta)",
                "Dota 2 folder not set (…/steamapps/common/dota 2 beta)",
                "Не вказано теку Dota 2 (…/steamapps/common/dota 2 beta)"),
    "backup": ("Сделан бэкап существующего pak01_dir.vpk → {f}", "Backed up existing pak01_dir.vpk → {f}",
               "Зроблено резервну копію pak01_dir.vpk → {f}"),
    "all_removed": ("Все моды удалены из игры.", "All mods removed from the game.", "Усі моди видалено з гри."),
    "mod_files": ("  + {m}: {n} файлов", "  + {m}: {n} files", "  + {m}: {n} файлів"),
    "not_vpk": ("{f}: это не VPK", "{f}: not a VPK file", "{f}: це не VPK"),
    "need_7z": ("Мод в .7z — установите: pip install py7zr", "Mod is .7z — install: pip install py7zr",
                "Мод у .7z — встановіть: pip install py7zr"),
    "bad_format": ("Формат не поддерживается: {f} (распакуйте вручную и укажите .vpk)",
                   "Unsupported format: {f} (unpack manually and choose the .vpk)",
                   "Формат не підтримується: {f} (розпакуйте вручну та вкажіть .vpk)"),
    "empty_archive": ("В архиве не найдено ни .vpk, ни файлов игры", "No .vpk or game files found in archive",
                      "В архіві не знайдено ні .vpk, ні файлів гри"),
    "need_tk": ("Нужен tkinter (на Linux: sudo apt install python3-tk)", "tkinter is required (Linux: sudo apt install python3-tk)",
                "Потрібен tkinter (Linux: sudo apt install python3-tk)"),
}


def set_lang(code):
    global _LANG
    _LANG = code if code in UI_LANGS else "ru"


def tr(key, **kw):
    vals = STRINGS[key]
    s = vals[list(UI_LANGS).index(_LANG)]
    return s.format(**kw) if kw else s


def norm(s: str) -> str:
    """Нормализация имени для сравнения: только буквы/цифры в нижнем регистре."""
    s = urllib.parse.unquote(s)
    s = s.replace("С", "C").replace("с", "c")  # кириллица в названиях встречается
    return re.sub(r"[^0-9a-zа-яё]+", "", s.lower())


# ----------------------------------------------------------------------------
# Сеть + кэш
# ----------------------------------------------------------------------------
def safe_url(url: str) -> str:
    """Экранирует пробелы/кириллицу в URL (превью часто с пробелами в имени)."""
    return urllib.parse.quote(url, safe=":/?&=%@+,;#~!$'()*[]")


def http_get(url: str, timeout=60, headers=None) -> bytes:
    url = safe_url(url)
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def cached_get(url: str, max_age=6 * 3600, binary=False):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = CACHE_DIR / (re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:] + f"_{zlib.crc32(url.encode()):08x}")
    if key.exists() and time.time() - key.stat().st_mtime < max_age:
        data = key.read_bytes()
    else:
        try:
            data = http_get(url)
            key.write_bytes(data)
        except Exception:
            if key.exists():  # оффлайн — берём старый кэш
                data = key.read_bytes()
            else:
                raise
    return data if binary else data.decode("utf-8", "replace")


def download_file(url: str, dest: Path, progress=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(safe_url(url), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    # Git LFS pointer?
    with open(tmp, "rb") as f:
        head = f.read(64)
    if head.startswith(b"version https://git-lfs"):
        tmp.unlink()
        raise LFSPointer()
    tmp.replace(dest)


class LFSPointer(Exception):
    pass


# ----------------------------------------------------------------------------
# Парсинг сайта
# ----------------------------------------------------------------------------
class ModCardParser(HTMLParser):
    """Собирает карточки модов: <a href="...?category=X&mod=Name"> + <img> + текст."""

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.mods = {}          # name -> dict
        self.stack = []         # открытые <a> с модом
        self.depth = 0
        self.last_img = None    # картинка, встреченная перед ссылкой
        self.categories = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            href = a.get("href") or ""
            m = re.search(r"category-([A-Za-z0-9_-]+)\.html", href)
            if m:
                self.categories.setdefault(m.group(1), None)
            if "mod=" in href:
                full = urllib.parse.urljoin(self.base, href)
                q = urllib.parse.parse_qs(urllib.parse.urlparse(full).query)
                name = (q.get("mod") or [""])[0].strip()
                cat = (q.get("category") or [""])[0].strip()
                if name:
                    card = self.mods.setdefault(name, {
                        "name": name, "category": cat, "page": full,
                        "preview": None, "text": [], "attrs": {}})
                    for k, v in a.items():
                        if k.startswith("data-") and v:
                            card["attrs"][k[5:]] = v
                        if k == "title" and v:
                            card["attrs"]["title"] = v
                    if self.last_img and not card["preview"]:
                        card["preview"] = self.last_img
                    self.stack.append(card)
                    return
        if tag in ("img", "source", "video"):
            cand = [a.get(k) for k in ("data-src", "data-lazy-src", "data-original", "poster", "src")]
            cand += [(a.get("srcset") or a.get("data-srcset") or "").split(" ")[0]]
            cand = [c for c in cand if c and not c.startswith("data:")
                    and not re.search(r"placeholder|blank|loading|spinner|\.svg$", c, re.I)]
            src = cand[0] if cand else None
            if src:
                src = urllib.parse.urljoin(self.base, src)
                if self.stack and not self.stack[-1]["preview"]:
                    self.stack[-1]["preview"] = src
                self.last_img = src
        if self.stack:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "a" and self.stack:
            self.stack.pop()
            self.last_img = None
        elif self.stack and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        t = data.strip()
        if t and self.stack:
            card = self.stack[-1]
            if t != card["name"] and t not in card["text"]:
                card["text"].append(t)


class SiteClient:
    def __init__(self, log):
        self.log = log

    def categories(self):
        try:
            html = cached_get(SITE)
            p = ModCardParser(SITE)
            p.feed(html)
            # подписи категорий из текста ссылок
            names = dict(re.findall(r'category-([A-Za-z0-9_-]+)\.html"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,40})<', html))
            slugs = [s for s in p.categories if s not in NON_MOD_CATEGORIES]
            if slugs:
                fb = dict(FALLBACK_CATEGORIES)
                def clean(t):
                    t = re.sub(r"^\s*dota\s*2\s+", "", t.strip(), flags=re.I)
                    return re.sub(r"\s+mods\s*$", "", t, flags=re.I) or t
                return [(s, clean(names.get(s) or fb.get(s) or s)) for s in slugs]
        except Exception as e:
            self.log(tr("home_fail", e=e))
        return list(FALLBACK_CATEGORIES)

    def mods(self, slug):
        url = urllib.parse.urljoin(SITE, f"category-{slug}.html")
        html = cached_get(url)
        p = ModCardParser(url)
        p.feed(html)
        mods = list(p.mods.values())
        for m in mods:
            m["category"] = m["category"] or slug
            m["text"] = " · ".join(m["text"])
        return mods


# ----------------------------------------------------------------------------
# Поиск файлов модов в репозитории
# ----------------------------------------------------------------------------
class FileIndex:
    """Индекс файлов модов (.vpk/.zip/...) из репозитория и релизов."""

    def __init__(self, log):
        self.log = log
        self.previews = {}  # norm(имя) -> [dict(path, branch)]
        self.entries = []   # dict(path, branch, size, source)
        self.ready = False

    def build(self):
        seen = set()
        for br in BRANCHES:
            files = self._github_tree(br) or self._jsdelivr_tree(br)
            for path, size in files:
                low = path.lower()
                if "preview" in low and low.endswith(IMG_EXTS + VIDEO_EXTS):
                    stem = norm(path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
                    self.previews.setdefault(stem, []).append({"path": path, "branch": br})
                    continue
                if low.endswith(MOD_EXTS) and (br, path) not in seen:
                    seen.add((br, path))
                    self.entries.append({"path": path, "branch": br, "size": size, "source": "repo"})
        for asset in self._releases():
            self.entries.append(asset)
        self.ready = True
        self.log(tr("index_found", n=len(self.entries)))

    def _github_tree(self, branch):
        try:
            data = json.loads(cached_get(
                f"https://api.github.com/repos/{OWNER}/{REPO}/git/trees/{branch}?recursive=1",
                max_age=12 * 3600))
            if data.get("truncated"):
                self.log(tr("tree_trunc", b=branch))
                return self._jsdelivr_tree(branch) or [(t["path"], t.get("size", 0)) for t in data.get("tree", []) if t.get("type") == "blob"]
            return [(t["path"], t.get("size", 0)) for t in data.get("tree", []) if t.get("type") == "blob"]
        except Exception:
            return []

    def _jsdelivr_tree(self, branch):
        try:
            data = json.loads(cached_get(
                f"https://data.jsdelivr.com/v1/packages/gh/{OWNER}/{REPO}@{branch}?structure=flat",
                max_age=12 * 3600))
            return [(f["name"].lstrip("/"), f.get("size", 0)) for f in data.get("files", [])]
        except Exception:
            return []

    def _releases(self):
        out = []
        try:
            rel = json.loads(cached_get(
                f"https://api.github.com/repos/{OWNER}/{REPO}/releases?per_page=100", max_age=12 * 3600))
            for r in rel:
                for a in r.get("assets", []):
                    if a["name"].lower().endswith(MOD_EXTS):
                        out.append({"path": a["name"], "url": a["browser_download_url"],
                                    "size": a.get("size", 0), "source": "release"})
        except Exception:
            pass
        return out

    def find(self, mod):
        """Подбор файла для мода по категории + имени/имени превью."""
        names = {norm(mod["name"])}
        if mod.get("preview"):
            stem = urllib.parse.unquote(mod["preview"].rsplit("/", 1)[-1]).rsplit(".", 1)[0]
            names.add(norm(stem))
        cat = norm(mod.get("category", ""))

        def score(e):
            p = e["path"]
            stem = norm(p.rsplit("/", 1)[-1].rsplit(".", 1)[0])
            parent = norm(p.rsplit("/", 2)[-2]) if p.count("/") >= 1 else ""
            in_cat = cat and cat in norm(p.rsplit("/", 1)[0])
            s = 0.0
            if stem in names or (parent in names and stem in ("pak01dir", "pak01", "")):
                s = 1.0
            else:
                s = max(SequenceMatcher(None, stem, n).ratio() for n in names)
            if "preview" in p.lower() or "/assets/" in p.lower():
                s -= 0.5
            return s + (0.2 if in_cat else 0.0)

        if not self.entries:
            return None
        best = max(self.entries, key=score)
        return best if score(best) >= 0.92 else None

    def find_previews(self, mod):
        """Картинки-превью для мода из репозитория (сначала из его категории)."""
        names = [norm(mod["name"])]
        if mod.get("preview"):
            names.append(norm(urllib.parse.unquote(mod["preview"].rsplit("/", 1)[-1]).rsplit(".", 1)[0]))
        cat = norm(mod.get("category", ""))
        out = []
        for n in names:
            for e in self.previews.get(n, []):
                if e not in out:
                    out.append(e)
        out.sort(key=lambda e: (cat not in norm(e["path"]), not e["path"].lower().endswith(IMG_EXTS)))
        return out

    @staticmethod
    def preview_urls(entry):
        q = urllib.parse.quote(entry["path"])
        br = entry["branch"]
        return [f"https://cdn.jsdelivr.net/gh/{OWNER}/{REPO}@{br}/{q}",
                f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{br}/{q}"]

    @staticmethod
    def urls(entry):
        if entry.get("url"):
            return [entry["url"]]
        q = urllib.parse.quote(entry["path"])
        br = entry["branch"]
        return [f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{br}/{q}",
                f"https://media.githubusercontent.com/media/{OWNER}/{REPO}/{br}/{q}",
                f"https://cdn.jsdelivr.net/gh/{OWNER}/{REPO}@{br}/{q}"]


# ----------------------------------------------------------------------------
# VPK: чтение (v1/v2) и запись (v1)
# ----------------------------------------------------------------------------
VPK_SIG = 0x55AA1234


def _cstr(buf, pos):
    end = buf.index(b"\0", pos)
    return buf[pos:end].decode("utf-8", "replace"), end + 1


def read_vpk(path) -> dict:
    """Возвращает {"путь/файл.ext": bytes}. path — *_dir.vpk или одиночный .vpk."""
    path = Path(path)
    raw = path.read_bytes()
    sig, ver, tree_size = struct.unpack_from("<III", raw, 0)
    if sig != VPK_SIG:
        raise ValueError(tr("not_vpk", f=path.name))
    header = 12 if ver == 1 else 28
    tree = raw[header:header + tree_size]
    data_base = header + tree_size
    files, pos = {}, 0
    archives = {}
    while True:
        ext, pos = _cstr(tree, pos)
        if not ext:
            break
        while True:
            d, pos = _cstr(tree, pos)
            if not d:
                break
            while True:
                name, pos = _cstr(tree, pos)
                if not name:
                    break
                crc, pre_len, idx, off, length, _t = struct.unpack_from("<IHHIIH", tree, pos)
                pos += 18
                pre = tree[pos:pos + pre_len]
                pos += pre_len
                if length == 0:
                    body = b""
                elif idx == 0x7FFF:
                    body = raw[data_base + off:data_base + off + length]
                else:
                    if idx not in archives:
                        base = re.sub(r"_dir$", "", path.stem)
                        archives[idx] = (path.parent / f"{base}_{idx:03d}.vpk").read_bytes()
                    body = archives[idx][off:off + length]
                full = name if ext == " " else f"{name}.{ext}"
                if d != " ":
                    full = f"{d}/{full}"
                files[full.lower()] = pre + body
    return files


def write_vpk(path, files: dict):
    """Пишет одиночный VPK v1 (всё внутри _dir-файла)."""
    tree = {}
    for full, data in files.items():
        full = full.replace("\\", "/").strip("/").lower()
        d, _, fn = full.rpartition("/")
        name, dot, ext = fn.rpartition(".")
        if not dot:
            name, ext = fn, " "
        tree.setdefault(ext, {}).setdefault(d or " ", []).append((name, data))
    tb, body, off = bytearray(), bytearray(), 0
    for ext in sorted(tree):
        tb += ext.encode() + b"\0"
        for d in sorted(tree[ext]):
            tb += d.encode() + b"\0"
            for name, data in sorted(tree[ext][d]):
                tb += name.encode() + b"\0"
                tb += struct.pack("<IHHIIH", zlib.crc32(data) & 0xFFFFFFFF, 0, 0x7FFF, off, len(data), 0xFFFF)
                body += data
                off += len(data)
            tb += b"\0"
        tb += b"\0"
    tb += b"\0"
    with open(path, "wb") as f:
        f.write(struct.pack("<III", VPK_SIG, 1, len(tb)))
        f.write(tb)
        f.write(body)


def extract_mod(archive: Path) -> dict:
    """Достаёт файлы игры из скачанного мода (.vpk или .zip)."""
    low = archive.name.lower()
    if low.endswith(".vpk"):
        return read_vpk(archive)
    if low.endswith(".zip"):
        tmp = APP_DIR / "tmp" / archive.stem
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                target = (tmp / info.filename).resolve()
                if not str(target).startswith(str(tmp.resolve())):
                    continue  # защита от zip-slip
                if not info.is_dir():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(z.read(info))
        return extract_folder(tmp)
    if low.endswith(".7z"):
        try:
            import py7zr  # type: ignore
        except ImportError:
            raise RuntimeError(tr("need_7z"))
        tmp = APP_DIR / "tmp" / archive.stem
        shutil.rmtree(tmp, ignore_errors=True)
        with py7zr.SevenZipFile(archive) as z:
            z.extractall(tmp)
        return extract_folder(tmp)
    raise RuntimeError(tr("bad_format", f=archive.name))


def extract_folder(root: Path) -> dict:
    files = {}
    vpks = [p for p in root.rglob("*.vpk") if not re.search(r"_\d{3}\.vpk$", p.name)]
    for v in vpks:
        files.update(read_vpk(v))
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() != ".vpk":
            parts = [x.lower() for x in p.relative_to(root).parts]
            for i, part in enumerate(parts):
                if part in GAME_TOP_DIRS:
                    files["/".join(parts[i:])] = p.read_bytes()
                    break
    if not files:
        raise RuntimeError(tr("empty_archive"))
    return files


# ----------------------------------------------------------------------------
# Dota 2
# ----------------------------------------------------------------------------
def steam_roots():
    roots = []
    if sys.platform.startswith("win"):
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for val in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(Path(winreg.QueryValueEx(k, val)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    elif sys.platform == "darwin":
        roots.append(Path.home() / "Library/Application Support/Steam")
    else:
        roots += [Path.home() / ".steam/steam", Path.home() / ".local/share/Steam",
                  Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    return [r for r in roots if r.exists()]


def find_dota():
    libs = []
    for root in steam_roots():
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text("utf-8", "replace")):
                libs.append(Path(p.replace("\\\\", "\\")))
    for lib in libs:
        d = lib / "steamapps" / "common" / "dota 2 beta"
        if (d / "game" / "dota").exists():
            return str(d)
    return ""


# ----------------------------------------------------------------------------
# Конфиг и установка
# ----------------------------------------------------------------------------
class Config:
    def __init__(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.data = {"dota_path": "", "lang_folder": "dota_english", "ui_lang": "ru", "guide_seen": False, "installed": []}
        if CONFIG_FILE.exists():
            try:
                self.data.update(json.loads(CONFIG_FILE.read_text("utf-8")))
            except Exception:
                pass
        if not self.data["dota_path"]:
            self.data["dota_path"] = find_dota()

    def save(self):
        CONFIG_FILE.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")

    @property
    def installed(self):
        return self.data["installed"]  # список dict(name, category, file)

    def is_installed(self, mod):
        return any(m["name"] == mod["name"] and m["category"] == mod["category"] for m in self.installed)


def apply_to_dota(cfg: Config, log):
    dota = Path(cfg.data["dota_path"])
    if not (dota / "game" / "dota").exists():
        raise RuntimeError(tr("no_dota"))
    target_dir = dota / "game" / cfg.data["lang_folder"]
    target = target_dir / "pak01_dir.vpk"
    marker = target_dir / MARKER_NAME

    if target.exists() and not marker.exists():
        bak = target.with_name(f"pak01_dir.vpk.backup_{int(time.time())}")
        shutil.copy2(target, bak)
        log(tr("backup", f=bak.name))

    if not cfg.installed:
        if target.exists() and marker.exists():
            target.unlink()
            marker.unlink()
        log(tr("all_removed"))
        return 0, []

    merged, owner, conflicts = {}, {}, []
    for m in cfg.installed:
        files = extract_mod(Path(m["file"]))
        for k, v in files.items():
            if k in owner and owner[k] != m["name"]:
                conflicts.append((k, owner[k], m["name"]))
            merged[k] = v
            owner[k] = m["name"]
        log(tr("mod_files", m=m["name"], n=len(files)))
    target_dir.mkdir(parents=True, exist_ok=True)
    write_vpk(target, merged)
    marker.write_text(json.dumps({"mods": [m["name"] for m in cfg.installed],
                                  "time": time.ctime()}, ensure_ascii=False), "utf-8")
    return len(merged), conflicts


def remove_from_dota(cfg: Config, log):
    """Удаляет собранный лаунчером pak01_dir.vpk из всех папок языка. Список модов не трогает."""
    game = Path(cfg.data["dota_path"]) / "game"
    if not (game / "dota").exists():
        raise RuntimeError(tr("no_dota"))
    removed = []
    for marker in game.glob("*/" + MARKER_NAME):
        folder = marker.parent
        vpk = folder / "pak01_dir.vpk"
        if vpk.exists():
            vpk.unlink()
        marker.unlink()
        removed.append(folder.name)
        log(tr("removed_from", f=folder.name))
    return removed


def launch_option(lang_folder):
    return "-language " + (lang_folder[5:] if lang_folder.startswith("dota_") else lang_folder)


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.cfg = Config()
        set_lang(self.cfg.data.get("ui_lang", "ru"))
        self.q = queue.Queue()
        self.site = SiteClient(self.log)
        self.index = FileIndex(self.log)
        self.cats = []
        self.cat_idx = 0          # 0 = «Все моды», дальше категории
        self.mods_by_cat = {}
        self.current = []
        self.selected = None
        self.preview_img = None
        self.img_cache = {}
        self.thumb_pil = {}
        self.thumb_tk = {}
        self.pool = ThreadPoolExecutor(max_workers=6)
        self.placeholder = None
        self.cards = []
        self.shown = 0
        self.cols = 3
        self.more_btn = None
        self.log_lines = []
        self.log_visible = False

        root.title(tr("title"))
        root.geometry("1280x800")
        root.minsize(980, 620)
        root.configure(bg=C["bg"])
        self._setup_style()
        self._build()
        self.root.after(100, self._pump)
        self.bg(self._load_start)
        if not HAS_PIL:
            self.bg(self._auto_pillow)
        if not self.cfg.data.get("guide_seen"):
            self.root.after(700, lambda: self.open_guide(first=True))
        elif not self.cfg.data["dota_path"]:
            self.root.after(600, self.open_settings)

    # ------------------------------------------------------------------ стиль
    def _setup_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=C["bg"], foreground=C["text"], fieldbackground=C["field"],
                     bordercolor=C["border"], lightcolor=C["panel"], darkcolor=C["panel"],
                     troughcolor=C["panel"], font=(FONT, 10))
        st.configure("TFrame", background=C["bg"])
        st.configure("TLabel", background=C["bg"], foreground=C["text"])
        st.configure("TCombobox", fieldbackground=C["field"], background=C["card"], foreground=C["text"],
                     arrowcolor=C["text"], selectbackground=C["field"], selectforeground=C["text"], padding=5)
        st.map("TCombobox", fieldbackground=[("readonly", C["field"])], foreground=[("readonly", C["text"])])
        st.configure("Vertical.TScrollbar", background=C["card"], troughcolor=C["bg"], bordercolor=C["bg"],
                     arrowcolor=C["muted"], gripcount=0, arrowsize=12)
        st.map("Vertical.TScrollbar", background=[("active", C["hover"])])
        st.configure("Thin.Horizontal.TProgressbar", background=C["accent"], troughcolor=C["panel"],
                     bordercolor=C["panel"], lightcolor=C["accent"], darkcolor=C["accent"], thickness=4)
        self.root.option_add("*TCombobox*Listbox.background", C["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
        self.root.option_add("*TCombobox*Listbox.font", (FONT, 10))

    def button(self, parent, text, cmd, kind="normal", **kw):
        colors = {"accent": (C["accent"], C["accent_h"], "#ffffff"),
                  "normal": (C["card"], C["hover"], C["text"]),
                  "ghost": (C["panel"], C["card"], C["text"]),
                  "danger": (C["card"], "#5a2a2a", "#ff8a80")}[kind]
        b = tk.Button(parent, text=text, command=cmd, bg=colors[0], fg=colors[2], activebackground=colors[1],
                      activeforeground=colors[2], relief="flat", bd=0, cursor="hand2",
                      font=(FONT, 11 if kind == "accent" else 10, "bold" if kind == "accent" else "normal"),
                      padx=kw.pop("padx", 14), pady=kw.pop("pady", 7), highlightthickness=0, **kw)
        b.bind("<Enter>", lambda e: b.configure(bg=colors[1]))
        b.bind("<Leave>", lambda e: b.configure(bg=colors[0]))
        return b

    # ------------------------------------------------------------------ интерфейс
    def _build(self):
        # --- шапка
        head = tk.Frame(self.root, bg=C["panel"], height=64)
        head.pack(fill="x")
        logo = tk.Frame(head, bg=C["panel"])
        logo.pack(side="left", padx=(18, 24), pady=10)
        tk.Label(logo, text="D2PFX", bg=C["panel"], fg=C["accent"], font=(FONT, 18, "bold")).pack(anchor="w")
        tk.Label(logo, text=tr("subtitle"), bg=C["panel"], fg=C["muted"], font=(FONT, 9)).pack(anchor="w")

        sbox = tk.Frame(head, bg=C["field"], highlightthickness=1, highlightbackground=C["border"],
                        highlightcolor=C["accent"])
        sbox.pack(side="left", fill="x", expand=True, pady=14)
        tk.Label(sbox, text="⌕", bg=C["field"], fg=C["muted"], font=(FONT, 11)).pack(side="left", padx=(10, 2))
        self.search_var = tk.StringVar()
        self.search = tk.Entry(sbox, textvariable=self.search_var, bg=C["field"], fg=C["text"], relief="flat",
                               insertbackground=C["text"], font=(FONT, 11), bd=0)
        self.search.pack(side="left", fill="x", expand=True, ipady=7, padx=(2, 10))
        self._ph_active = False
        self._set_placeholder()
        self.search.bind("<FocusIn>", self._clear_placeholder)
        self.search.bind("<FocusOut>", lambda e: self._set_placeholder())
        self.search_var.trace_add("write", lambda *a: None if self._ph_active else self._debounced_refresh())
        self.search.bind("<Escape>", lambda e: (self.search_var.set(""), self.root.focus()))

        right = tk.Frame(head, bg=C["panel"])
        right.pack(side="right", padx=14)
        self.apply_btn = self.button(right, tr("apply"), self.apply, "accent", padx=18, pady=9)
        self.apply_btn.pack(side="right", padx=(8, 0))
        self.button(right, "▶ " + tr("run"), self.run_dota, "normal").pack(side="right", padx=(8, 0))
        self.button(right, "⚙ " + tr("settings"), self.open_settings, "normal").pack(side="right", padx=(8, 0))
        self.button(right, "? " + tr("guide"), self.open_guide, "normal").pack(side="right", padx=(8, 0))

        # --- основная часть
        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill="both", expand=True)

        # категории
        side = tk.Frame(body, bg=C["panel"], width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text=tr("categories").upper(), bg=C["panel"], fg=C["muted"],
                 font=(FONT, 9, "bold")).pack(anchor="w", padx=16, pady=(14, 6))
        cf = tk.Frame(side, bg=C["panel"])
        cf.pack(fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        self.cat_list = tk.Listbox(cf, bg=C["panel"], fg=C["text"], selectbackground=C["accent"],
                                   selectforeground="#ffffff", relief="flat", bd=0, highlightthickness=0,
                                   activestyle="none", exportselection=False, font=(FONT, 10))
        cs = ttk.Scrollbar(cf, orient="vertical", command=self.cat_list.yview)
        self.cat_list.configure(yscrollcommand=cs.set)
        cs.pack(side="right", fill="y")
        self.cat_list.pack(side="left", fill="both", expand=True)
        self.cat_list.bind("<<ListboxSelect>>", self.on_cat)

        # детали (справа)
        det = tk.Frame(body, bg=C["panel"], width=360)
        det.pack(side="right", fill="y")
        det.pack_propagate(False)
        self._build_details(det)

        # сетка модов
        mid = tk.Frame(body, bg=C["bg"])
        mid.pack(side="left", fill="both", expand=True)
        bar = tk.Frame(mid, bg=C["bg"])
        bar.pack(fill="x", padx=16, pady=(12, 4))
        self.section_lbl = tk.Label(bar, text="", bg=C["bg"], fg=C["text"], font=(FONT, 15, "bold"))
        self.section_lbl.pack(side="left")
        self.count_lbl = tk.Label(bar, text="", bg=C["bg"], fg=C["muted"], font=(FONT, 10))
        self.count_lbl.pack(side="left", padx=10, pady=(4, 0))
        tk.Label(bar, text=tr("hint_dbl"), bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side="right")

        gf = tk.Frame(mid, bg=C["bg"])
        gf.pack(fill="both", expand=True, padx=(8, 0))
        self.canvas = tk.Canvas(gf, highlightthickness=0, bg=C["bg"], bd=0)
        ys = ttk.Scrollbar(gf, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = tk.Frame(self.canvas, bg=C["bg"])
        self._grid_win = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        if not getattr(self, "_wheel_bound", False):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.root.bind_all(seq, self._on_wheel, add="+")
            self._wheel_bound = True
        self.empty_lbl = tk.Label(self.grid_frame, text=tr("loading"), bg=C["bg"], fg=C["muted"],
                                  font=(FONT, 12))
        self.empty_lbl.grid(row=0, column=0, padx=20, pady=40)

        # --- статус-бар + журнал
        self.progress = ttk.Progressbar(self.root, mode="determinate", style="Thin.Horizontal.TProgressbar")
        self.progress.pack(fill="x", side="bottom")
        self.log_frame = tk.Frame(self.root, bg=C["panel"])
        self.log_box = tk.Text(self.log_frame, height=8, wrap="word", state="disabled", bg=C["field"],
                               fg=C["muted"], relief="flat", bd=0, font=("Consolas", 9), padx=10, pady=6)
        self.log_box.pack(fill="both", expand=True)
        status = tk.Frame(self.root, bg=C["panel"])
        status.pack(fill="x", side="bottom")
        self.status_lbl = tk.Label(status, text=tr("ready"), bg=C["panel"], fg=C["muted"], anchor="w",
                                   font=(FONT, 9))
        self.status_lbl.pack(side="left", fill="x", expand=True, padx=12, pady=5)
        self.log_toggle = tk.Label(status, text=tr("log_show"), bg=C["panel"], fg=C["accent"],
                                   cursor="hand2", font=(FONT, 9))
        self.log_toggle.pack(side="right", padx=12)
        self.log_toggle.bind("<Button-1>", lambda e: self.toggle_log())
        if self.log_visible:
            self.log_frame.pack(fill="x", side="bottom", after=status)
            self.log_toggle.configure(text=tr("log_hide"))
        for line in self.log_lines:
            self._append_log(line)
        self.refresh_installed()

    def _build_details(self, det):
        pad = dict(padx=16)
        self.img_lbl = tk.Label(det, bg=C["card"], fg=C["muted"], text=tr("pick_mod_hint"),
                                font=(FONT, 10), width=40, height=10)
        self.img_lbl.pack(fill="x", pady=(16, 10), **pad)
        self.title_lbl = tk.Label(det, text=tr("pick_mod"), bg=C["panel"], fg=C["text"],
                                  font=(FONT, 14, "bold"), wraplength=320, justify="left", anchor="w")
        self.title_lbl.pack(fill="x", **pad)
        self.cat_lbl = tk.Label(det, text="", bg=C["panel"], fg=C["accent"], font=(FONT, 9, "bold"), anchor="w")
        self.cat_lbl.pack(fill="x", **pad)
        self.info = tk.Label(det, text="", bg=C["panel"], fg=C["muted"], font=(FONT, 9), wraplength=320,
                             justify="left", anchor="w")
        self.info.pack(fill="x", pady=(6, 10), **pad)
        self.inst_btn = self.button(det, tr("install"), self.toggle_install, "accent")
        self.inst_btn.pack(fill="x", **pad)
        row = tk.Frame(det, bg=C["panel"])
        row.pack(fill="x", pady=(6, 0), **pad)
        self.button(row, "↗ " + tr("open_site"), self.open_page, "normal").pack(side="left", fill="x", expand=True)
        self.button(row, "＋ " + tr("own_file"), self.pick_local, "normal").pack(side="left", fill="x",
                                                                              expand=True, padx=(6, 0))

        tk.Frame(det, bg=C["border"], height=1).pack(fill="x", pady=16, **pad)
        hdr = tk.Frame(det, bg=C["panel"])
        hdr.pack(fill="x", **pad)
        self.my_lbl = tk.Label(hdr, text=tr("my_mods", n=0), bg=C["panel"], fg=C["text"], font=(FONT, 11, "bold"))
        self.my_lbl.pack(side="left")
        clr = tk.Label(hdr, text=tr("remove_all"), bg=C["panel"], fg="#ff8a80", cursor="hand2", font=(FONT, 9))
        clr.pack(side="right")
        clr.bind("<Button-1>", lambda e: self.remove_all())
        tk.Label(det, text=tr("prio_hint"), bg=C["panel"], fg=C["muted"], font=(FONT, 8),
                 anchor="w").pack(fill="x", **pad)
        lf = tk.Frame(det, bg=C["panel"])
        lf.pack(fill="both", expand=True, pady=(6, 0), **pad)
        self.inst_list = tk.Listbox(lf, bg=C["field"], fg=C["text"], selectbackground=C["hover"],
                                    selectforeground=C["text"], relief="flat", bd=0, highlightthickness=0,
                                    activestyle="none", font=(FONT, 10))
        self.inst_list.pack(fill="both", expand=True)
        self.inst_list.bind("<Delete>", lambda e: self.remove_selected_installed())
        ib = tk.Frame(det, bg=C["panel"])
        ib.pack(fill="x", pady=(6, 14), **pad)
        self.button(ib, "↑", lambda: self.move(-1), "normal", padx=12).pack(side="left")
        self.button(ib, "↓", lambda: self.move(1), "normal", padx=12).pack(side="left", padx=4)
        self.button(ib, "✕ " + tr("remove"), self.remove_selected_installed, "danger").pack(side="right")
        self.button(det, "⌫ " + tr("uninstall_game"), self.uninstall_from_game, "danger").pack(
            fill="x", padx=16, pady=(0, 14))

    # ------------------------------------------------------------------ поиск
    def _set_placeholder(self):
        if not self.search_var.get():
            self._ph_active = True
            self.search.configure(fg=C["muted"])
            self.search_var.set(tr("search_ph"))

    def _clear_placeholder(self, *_):
        if self._ph_active:
            self._ph_active = False
            self.search.configure(fg=C["text"])
            self.search_var.set("")

    def search_text(self):
        return "" if self._ph_active else self.search_var.get().strip().lower()

    def _debounced_refresh(self):
        if getattr(self, "_deb", None):
            self.root.after_cancel(self._deb)
        self._deb = self.root.after(250, self._search_changed)

    def _search_changed(self):
        # при поиске в «Все моды» догружаем все категории
        if self.cat_idx == 0:
            self._ensure_all_loaded()
        self.refresh_mods()

    # ------------------------------------------------------------------ язык и настройки
    def open_settings(self):
        win = tk.Toplevel(self.root, bg=C["panel"])
        win.title(tr("settings"))
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()
        f = tk.Frame(win, bg=C["panel"], padx=22, pady=18)
        f.pack(fill="both")

        def lbl(t, top=12):
            tk.Label(f, text=t, bg=C["panel"], fg=C["muted"], font=(FONT, 9, "bold")).pack(anchor="w", pady=(top, 4))

        tk.Label(f, text="⚙ " + tr("settings"), bg=C["panel"], fg=C["text"], font=(FONT, 15, "bold")).pack(anchor="w")
        lbl(tr("ui_lang").rstrip(":").upper())
        lang_var = tk.StringVar(value=UI_LANGS[_LANG])
        ttk.Combobox(f, textvariable=lang_var, values=list(UI_LANGS.values()), state="readonly",
                     width=20).pack(anchor="w")

        lbl(tr("dota_dir").upper())
        prow = tk.Frame(f, bg=C["panel"])
        prow.pack(fill="x")
        path_var = tk.StringVar(value=self.cfg.data["dota_path"])
        tk.Entry(prow, textvariable=path_var, width=52, bg=C["field"], fg=C["text"], relief="flat",
                 insertbackground=C["text"], font=(FONT, 10)).pack(side="left", ipady=6, fill="x", expand=True)

        def browse():
            p = filedialog.askdirectory(parent=win, title=tr("dota_dir"))
            if p:
                path_var.set(p)

        def detect():
            p = find_dota()
            path_var.set(p) if p else messagebox.showwarning(tr("settings"), tr("not_detected"), parent=win)

        self.button(prow, tr("browse"), browse, "normal").pack(side="left", padx=(6, 0))
        self.button(prow, tr("auto_detect"), detect, "normal").pack(side="left", padx=(6, 0))
        ok_lbl = tk.Label(f, text="", bg=C["panel"], font=(FONT, 9))
        ok_lbl.pack(anchor="w", pady=(4, 0))

        def check(*_):
            good = (Path(path_var.get()) / "game" / "dota").exists()
            ok_lbl.configure(text=tr("path_ok") if good else tr("path_bad"), fg=C["ok"] if good else "#ff8a80")
        path_var.trace_add("write", check)
        check()

        lbl(tr("lang_folder").strip().rstrip(":").upper())
        lf_var = tk.StringVar(value=self.cfg.data["lang_folder"])
        ttk.Combobox(f, textvariable=lf_var, values=LANG_FOLDERS, width=20).pack(anchor="w")
        opt_lbl = tk.Label(f, text="", bg=C["panel"], fg=C["muted"], font=(FONT, 9), justify="left")
        opt_lbl.pack(anchor="w", pady=(6, 0))
        lf_var.trace_add("write", lambda *a: opt_lbl.configure(text=tr("launch_hint", o=launch_option(lf_var.get()))))
        opt_lbl.configure(text=tr("launch_hint", o=launch_option(lf_var.get())))

        btns = tk.Frame(f, bg=C["panel"])
        btns.pack(fill="x", pady=(18, 0))

        def save():
            self.cfg.data["dota_path"] = path_var.get().strip()
            self.cfg.data["lang_folder"] = lf_var.get().strip() or "dota_english"
            code = next(k for k, v in UI_LANGS.items() if v == lang_var.get())
            self.cfg.data["ui_lang"] = code
            self.cfg.save()
            win.destroy()
            if code != _LANG:
                self.change_ui_lang(code)

        self.button(btns, tr("save"), save, "accent").pack(side="right")
        self.button(btns, tr("cancel"), win.destroy, "normal").pack(side="right", padx=6)
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def change_ui_lang(self, code):
        set_lang(code)
        search = self.search_text()
        for w in self.root.winfo_children():
            w.destroy()
        self.selected = None
        self.placeholder = None
        self.root.title(tr("title"))
        self._build()
        if search:
            self._clear_placeholder()
            self.search_var.set(search)
        self._fill_cats(keep=True)

    # ------------------------------------------------------------------ фон / лог
    def bg(self, fn, *args):
        def run():
            try:
                fn(*args)
            except Exception as e:
                self.log(tr("err", e=e))
                traceback.print_exc()
        threading.Thread(target=run, daemon=True).start()

    def ui(self, fn, *args):
        self.q.put((fn, args))

    def _pump(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                try:
                    fn(*args)
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def log(self, msg):
        line = time.strftime("[%H:%M:%S] ") + msg

        def w():
            self.log_lines.append(line)
            self._append_log(line)
            self.status_lbl.configure(text=msg.replace("\n", " "))
        self.ui(w)

    def _append_log(self, line):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_frame.pack(fill="x", side="bottom", after=self.status_lbl.master)
            self.log_toggle.configure(text=tr("log_hide"))
        else:
            self.log_frame.pack_forget()
            self.log_toggle.configure(text=tr("log_show"))

    def set_progress(self, done, total):
        def w():
            self.progress["maximum"] = max(total, 1)
            self.progress["value"] = done if total else 0
        self.ui(w)

    def _auto_pillow(self):
        self.log(tr("pil_installing", py=sys.executable))
        ok, err = install_pillow()
        if ok:
            self.log(tr("pil_ok"))

            def done():
                self.thumb_pil.clear()
                self.thumb_tk.clear()
                self.refresh_mods()
            self.ui(done)
        else:
            self.log(tr("pil_fail", py=sys.executable, e=err))

    # ------------------------------------------------------------------ данные
    def _load_start(self):
        self.log(tr("loading_cats"))
        self.cats = self.site.categories()
        self.ui(self._fill_cats)
        self.log(tr("cats_loaded", n=len(self.cats)))
        self.index.build()
        self.log(tr("ready"))

        def retry():
            for k in [k for k, v in self.thumb_pil.items() if isinstance(v, str) and v not in ("loading", "video")]:
                del self.thumb_pil[k]
            self.img_cache = {k: v for k, v in self.img_cache.items() if not isinstance(v, str)}
            self.refresh_mods()
        self.ui(retry)

    def _fill_cats(self, keep=False):
        self.cat_list.delete(0, "end")
        self.cat_list.insert("end", "  ★  " + tr("all_mods"))
        for slug, title in self.cats:
            self.cat_list.insert("end", "      " + title)
        for i in range(self.cat_list.size()):
            self.cat_list.itemconfigure(i, background=C["panel"])
        idx = self.cat_idx if keep else (1 if self.cats else 0)
        self.cat_list.selection_set(idx)
        self.cat_idx = -1
        self.on_cat()

    def load_cat(self, slug):
        if slug in self.mods_by_cat:
            return
        try:
            mods = self.site.mods(slug)
            self.mods_by_cat[slug] = mods
            self.log(tr("cat_mods", s=slug, n=len(mods)))
        except Exception as e:
            self.mods_by_cat[slug] = []
            self.log(tr("cat_fail", s=slug, e=e))

    def _ensure_all_loaded(self):
        missing = [s for s, _ in self.cats if s not in self.mods_by_cat]
        if not missing or getattr(self, "_loading_all", False):
            return
        self._loading_all = True

        def run():
            try:
                for i, slug in enumerate(missing):
                    self.load_cat(slug)
                    self.set_progress(i + 1, len(missing))
                    if i % 5 == 4:
                        self.ui(self.refresh_mods)
            finally:
                self._loading_all = False
                self.set_progress(0, 0)
                self.ui(self.refresh_mods)
        self.bg(run)

    def on_cat(self, *_):
        sel = self.cat_list.curselection()
        if not sel or sel[0] == self.cat_idx:
            return
        self.cat_idx = sel[0]
        if self.cat_idx == 0:
            self._ensure_all_loaded()
            self.refresh_mods()
        else:
            slug = self.cats[self.cat_idx - 1][0]

            def run():
                self.load_cat(slug)
                self.ui(self.refresh_mods)
            self.bg(run)
            self.refresh_mods()

    def refresh_mods(self):
        s = self.search_text()
        if self.cat_idx <= 0:
            mods = [m for slug, _ in self.cats for m in self.mods_by_cat.get(slug, [])]
            title = tr("all_mods")
        else:
            slug, title = self.cats[self.cat_idx - 1]
            mods = self.mods_by_cat.get(slug)
            if mods is None:
                mods = []
        if s:
            mods = [m for m in mods if s in m["name"].lower() or s in m.get("text", "").lower()]
        self.section_lbl.configure(text=title)
        self.count_lbl.configure(text=tr("count", n=len(mods)))
        self.current = mods
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.cards, self.shown, self.more_btn = [], 0, None
        self.canvas.yview_moveto(0)
        if not mods:
            txt = tr("nothing_found") if s else tr("loading")
            tk.Label(self.grid_frame, text=txt, bg=C["bg"], fg=C["muted"], font=(FONT, 12)).grid(
                row=0, column=0, padx=20, pady=40)
            return
        self.show_more()

    # ------------------------------------------------------------------ плитка
    def _placeholder(self):
        if self.placeholder is None:
            self.placeholder = tk.PhotoImage(width=THUMB_W, height=THUMB_H)
            self.placeholder.put(C["thumb"], to=(0, 0, THUMB_W, THUMB_H))
        return self.placeholder

    def show_more(self):
        if self.more_btn is not None:
            self.more_btn.destroy()
            self.more_btn = None
        start, end = self.shown, min(self.shown + PAGE_SIZE, len(self.current))
        for i in range(start, end):
            self._make_card(i, self.current[i])
        self.shown = end
        rest = len(self.current) - end
        if rest > 0:
            self.more_btn = self.button(self.grid_frame, tr("show_more", n=rest), self.show_more, "normal", pady=10)
        self._layout()

    def _make_card(self, i, m):
        card = tk.Frame(self.grid_frame, bg=C["card"], highlightthickness=2,
                        highlightbackground=C["card"], cursor="hand2")
        img = tk.Label(card, image=self._placeholder(), bg=C["card"], bd=0)
        img.pack()
        cap = tk.Frame(card, bg=C["card"])
        cap.pack(fill="x", padx=10, pady=(8, 8))
        name = tk.Label(cap, text=m["name"], bg=C["card"], fg=C["text"], font=(FONT, 10, "bold"),
                        wraplength=THUMB_W - 50, justify="left", anchor="w")
        name.pack(side="left", fill="x", expand=True)
        badge = tk.Label(cap, text="", bg=C["card"], font=(FONT, 12, "bold"), cursor="hand2", width=2)
        badge.pack(side="right")
        sub = None
        if self.cat_idx == 0:
            sub = tk.Label(card, text=m["category"], bg=C["card"], fg=C["muted"], font=(FONT, 8), anchor="w")
            sub.pack(fill="x", padx=10, pady=(0, 8), before=cap)
        parts = [card, img, cap, name] + ([sub] if sub else [])

        def hover(on):
            if m is not self.selected:
                bgc = C["hover"] if on else C["card"]
                for w in parts + [badge]:
                    w.configure(bg=bgc)
                card.configure(highlightbackground=bgc)

        for w in parts:
            w.bind("<Button-1>", lambda e, k=i: self.select_mod(k))
            w.bind("<Double-1>", lambda e, k=i: (self.select_mod(k), self.toggle_install()))
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
        badge.bind("<Button-1>", lambda e, k=i: (self.select_mod(k), self.toggle_install()))
        self.cards.append({"mod": m, "card": card, "badge": badge, "img": img, "parts": parts})
        self._set_badge(m, badge)

        key = self.thumb_key(m)
        if HAS_PIL:
            if key in self.thumb_tk:
                img.configure(image=self.thumb_tk[key])
            elif key not in self.thumb_pil:
                self.thumb_pil[key] = "loading"
                self.pool.submit(self._load_thumb, m)
            elif isinstance(self.thumb_pil[key], str) and self.thumb_pil[key] != "loading":
                self._show_thumb_fail(img, self.thumb_pil[key])
        else:
            img.configure(text=tr("need_pil"), compound="center", fg=C["muted"], font=(FONT, 9))

    def _set_badge(self, m, badge):
        if self.cfg.is_installed(m):
            badge.configure(text="✔", fg=C["ok"])
        else:
            badge.configure(text="＋", fg=C["muted"])

    @staticmethod
    def thumb_key(m):
        return f"{m.get('category')}/{m['name']}"

    def preview_candidates(self, m):
        """Ссылки на картинку превью: со страницы сайта, из репозитория, по шаблону."""
        urls, video = [], False
        p = m.get("preview")
        if p:
            if p.lower().split("?")[0].endswith(VIDEO_EXTS):
                video = True
            else:
                urls.append(p)
        if self.index.ready:
            for e in self.index.find_previews(m):
                if e["path"].lower().endswith(VIDEO_EXTS):
                    video = True
                    continue
                urls += FileIndex.preview_urls(e)
        base = f"https://cdn.jsdelivr.net/gh/{OWNER}/{REPO}@mirror/assets/previews/{m.get('category')}/"
        stem = urllib.parse.quote(m["name"])
        urls += [base + stem + ext for ext in (".webp", ".png", ".jpg", ".gif")]
        seen, out = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out, video

    def fetch_preview(self, m):
        """Скачивает и открывает превью. Возвращает (PIL.Image | None, причина ошибки)."""
        urls, video = self.preview_candidates(m)
        last = ""
        for u in urls:
            try:
                data = cached_get(u, max_age=7 * 86400, binary=True)
                if data[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
                    last = "HTML вместо картинки"
                    continue
                im = Image.open(io.BytesIO(data))
                im.seek(0)
                return im.convert("RGBA"), ""
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
            except Exception as e:
                last = type(e).__name__ + (f": {e}" if str(e) else "")
        return None, ("video" if video else last or "нет ссылки")

    def _load_thumb(self, m):
        key = self.thumb_key(m)
        im, why = self.fetch_preview(m)
        if im is None:
            self.thumb_pil[key] = why or "fail"
            self._fail_count = getattr(self, "_fail_count", 0) + 1
            if self._fail_count <= 10:
                self.log(tr("preview_fail", m=m["name"], e=why))
        else:
            scale = max(THUMB_W / im.width, THUMB_H / im.height)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
            left, top = (im.width - THUMB_W) // 2, (im.height - THUMB_H) // 2
            self.thumb_pil[key] = im.crop((left, top, left + THUMB_W, top + THUMB_H))
        self.ui(self._apply_thumb, key)

    def _show_thumb_fail(self, img, why):
        txt = tr("video_preview") if why == "video" else tr("no_preview")
        img.configure(text=txt, compound="center", fg=C["muted"], font=(FONT, 9))

    def _apply_thumb(self, key):
        pil = self.thumb_pil.get(key)
        if pil is None or pil == "loading":
            return
        for c in self.cards:
            if self.thumb_key(c["mod"]) != key or not c["img"].winfo_exists():
                continue
            if isinstance(pil, str):
                self._show_thumb_fail(c["img"], pil)
            else:
                if key not in self.thumb_tk:
                    self.thumb_tk[key] = ImageTk.PhotoImage(pil)
                c["img"].configure(image=self.thumb_tk[key], text="")

    def _layout(self):
        cols = max(1, self.cols)
        for k, c in enumerate(self.cards):
            c["card"].grid(row=k // cols, column=k % cols, padx=6, pady=6, sticky="nsew")
        for col in range(cols):
            self.grid_frame.grid_columnconfigure(col, weight=0, minsize=CARD_W)
        if self.more_btn is not None:
            self.more_btn.grid(row=len(self.cards) // cols + 1, column=0, columnspan=cols, pady=14, sticky="ew")

    def _on_canvas_resize(self, e):
        self.canvas.itemconfigure(self._grid_win, width=e.width)
        cols = max(1, e.width // (CARD_W + 12))
        if cols != self.cols:
            self.cols = cols
            self._layout()

    def _on_wheel(self, e):
        try:
            w = self.root.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return
        target = None
        while w is not None:
            if w is self.canvas:
                target = self.canvas
                break
            if isinstance(w, (tk.Listbox, tk.Text)):
                return
            w = w.master
        if target is None:
            return
        if e.num == 4:
            d = -3
        elif e.num == 5:
            d = 3
        else:
            d = -int(e.delta / 120) * 3 if abs(e.delta) >= 120 else -e.delta
        self.canvas.yview_scroll(d, "units")

    def update_statuses(self):
        for c in self.cards:
            if c["badge"].winfo_exists():
                self._set_badge(c["mod"], c["badge"])

    def select_mod(self, i):
        m = self.current[i]
        self.selected = m
        for c in self.cards:
            sel = c["mod"] is m
            bgc = C["hover"] if sel else C["card"]
            for w in c["parts"] + [c["badge"]]:
                w.configure(bg=bgc)
            c["card"].configure(highlightbackground=C["accent"] if sel else C["card"])
        self.on_mod(m)

    # ------------------------------------------------------------------ детали
    def on_mod(self, m):
        self.selected = m
        self.title_lbl.configure(text=m["name"])
        self.cat_lbl.configure(text=m["category"].upper())
        lines = []
        if m.get("text"):
            lines.append(m["text"])
        for k, v in m.get("attrs", {}).items():
            lines.append(f"{k}: {v}")
        if self.index.ready:
            e = self.index.find(m)
            if e:
                lines.append("▣ " + e["path"].rsplit("/", 1)[-1] +
                             (tr("mb", n=e["size"] / 1048576) if e.get("size") else ""))
            else:
                lines.append("⚠ " + tr("file_not_found"))
        else:
            lines.append(tr("index_building"))
        self.info.configure(text="\n".join(lines))
        self._update_inst_btn()
        if HAS_PIL:
            self.img_lbl.configure(image="", text=tr("loading"), width=40, height=10)
            self.bg(self._load_preview, m)
        else:
            self.img_lbl.configure(image="", text=tr("need_pil"))

    def _update_inst_btn(self):
        if not self.selected:
            return
        if self.cfg.is_installed(self.selected):
            self.inst_btn.configure(text="✕ " + tr("remove"), bg=C["card"], fg="#ff8a80")
            self.inst_btn.bind("<Leave>", lambda e: self.inst_btn.configure(bg=C["card"]))
            self.inst_btn.bind("<Enter>", lambda e: self.inst_btn.configure(bg="#5a2a2a"))
        else:
            self.inst_btn.configure(text="＋ " + tr("install"), bg=C["accent"], fg="#ffffff")
            self.inst_btn.bind("<Leave>", lambda e: self.inst_btn.configure(bg=C["accent"]))
            self.inst_btn.bind("<Enter>", lambda e: self.inst_btn.configure(bg=C["accent_h"]))

    def _load_preview(self, m):
        key = self.thumb_key(m)
        if key not in self.img_cache:
            im, why = self.fetch_preview(m)
            if im is not None:
                im.thumbnail((328, 200))
            self.img_cache[key] = im if im is not None else why
        url = key

        def show():
            if self.selected is not m:
                return
            img = self.img_cache.get(url)
            if img is None or isinstance(img, str):
                txt = tr("video_preview") if img == "video" else tr("no_preview")
                self.img_lbl.configure(image="", text=txt, width=40, height=10)
                return
            self.preview_img = ImageTk.PhotoImage(img)
            self.img_lbl.configure(image=self.preview_img, text="", width=0, height=0)
        self.ui(show)

    def open_page(self):
        if self.selected:
            webbrowser.open(self.selected["page"])

    # ------------------------------------------------------------------ установка
    def toggle_install(self):
        m = self.selected
        if not m:
            return
        if self.cfg.is_installed(m):
            self.cfg.data["installed"] = [x for x in self.cfg.installed
                                          if not (x["name"] == m["name"] and x["category"] == m["category"])]
            self.cfg.save()
            self.after_change(tr("removed", m=m["name"]))
        else:
            self.bg(self._download_and_add, m)

    def _download_and_add(self, m):
        if not self.index.ready:
            self.log(tr("wait_index"))
            return
        e = self.index.find(m)
        if not e:
            self.log(tr("no_file", m=m["name"]))
            return
        fname = e["path"].rsplit("/", 1)[-1]
        dest = DL_DIR / re.sub(r"[^\w.-]+", "_", m["category"]) / re.sub(r'[<>:"/\\|?*]+', "_", f"{m['name']}__{fname}")
        if not dest.exists():
            self.log(tr("downloading", m=m["name"]))
            err = None
            for url in FileIndex.urls(e):
                try:
                    download_file(url, dest, self.set_progress)
                    err = None
                    break
                except Exception as ex:
                    err = ex
            self.set_progress(0, 0)
            if err:
                self.log(tr("dl_fail", m=m["name"], e=err))
                return
        try:
            n = len(extract_mod(dest))
        except Exception as ex:
            self.log(f"«{m['name']}»: {ex}")
            return
        self._add_installed(m, dest, n)

    def _add_installed(self, m, path, n):
        def w():
            if not self.cfg.is_installed(m):
                self.cfg.installed.append({"name": m["name"], "category": m["category"], "file": str(path)})
                self.cfg.save()
            self.after_change(tr("added", m=m["name"], n=n))
        self.ui(w)

    def pick_local(self):
        p = filedialog.askopenfilename(title=tr("mod_file"),
                                       filetypes=[(tr("ft_mods"), "*.vpk *.zip *.7z"), (tr("ft_all"), "*.*")])
        if not p:
            return
        m = self.selected or {"name": Path(p).stem, "category": "local"}
        dest = DL_DIR / "local" / Path(p).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        try:
            n = len(extract_mod(dest))
        except Exception as ex:
            messagebox.showerror(tr("error_title"), str(ex))
            return
        self.cfg.data["installed"] = [x for x in self.cfg.installed
                                      if not (x["name"] == m["name"] and x["category"] == m["category"])]
        self._add_installed(m, dest, n)

    def after_change(self, msg):
        self.log(msg)
        self.refresh_installed()
        self.update_statuses()
        self._update_inst_btn()

    def refresh_installed(self):
        self.inst_list.delete(0, "end")
        for k, m in enumerate(self.cfg.installed, 1):
            self.inst_list.insert("end", f"  {k}.  {m['name']}")
        n = len(self.cfg.installed)
        self.my_lbl.configure(text=tr("my_mods", n=n))
        self.apply_btn.configure(text=tr("apply") + (f"  ({n})" if n else ""))

    def move(self, d):
        sel = self.inst_list.curselection()
        if not sel:
            return
        i, j = sel[0], sel[0] + d
        lst = self.cfg.installed
        if 0 <= j < len(lst):
            lst[i], lst[j] = lst[j], lst[i]
            self.cfg.save()
            self.refresh_installed()
            self.inst_list.selection_set(j)

    def remove_selected_installed(self):
        sel = self.inst_list.curselection()
        if sel:
            m = self.cfg.installed.pop(sel[0])
            self.cfg.save()
            self.after_change(tr("removed", m=m["name"]))

    def remove_all(self):
        if self.cfg.installed and messagebox.askyesno(tr("remove_all"), tr("confirm_all")):
            self.cfg.data["installed"] = []
            self.cfg.save()
            self.after_change(tr("cleared"))

    # ------------------------------------------------------------------ Dota
    def apply(self):
        if not (Path(self.cfg.data["dota_path"]) / "game" / "dota").exists():
            self.open_settings()
            return

        def run():
            self.log(tr("building"))
            try:
                n, conflicts = apply_to_dota(self.cfg, self.log)
            except Exception as e:
                self.log(tr("install_err", e=e))
                self.ui(messagebox.showerror, tr("error_title"), str(e))
                return
            for k, a, b in conflicts[:15]:
                self.log(tr("conflict", k=k, a=a, b=b))
            if n:
                self.log(tr("done", n=n, f=self.cfg.data["lang_folder"],
                            o=launch_option(self.cfg.data["lang_folder"])).replace("\n", " "))
                self.ui(self._done_dialog, n)
        self.bg(run)

    def _done_dialog(self, n):
        opt = launch_option(self.cfg.data["lang_folder"])
        win = tk.Toplevel(self.root, bg=C["panel"])
        win.title(tr("done_title"))
        win.transient(self.root)
        win.resizable(False, False)
        f = tk.Frame(win, bg=C["panel"], padx=24, pady=20)
        f.pack()
        tk.Label(f, text="✔ " + tr("done_title"), bg=C["panel"], fg=C["ok"], font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(f, text=tr("done_short", n=n), bg=C["panel"], fg=C["text"], font=(FONT, 10),
                 justify="left").pack(anchor="w", pady=(8, 12))
        tk.Label(f, text=tr("launch_step"), bg=C["panel"], fg=C["muted"], font=(FONT, 9),
                 justify="left").pack(anchor="w")
        row = tk.Frame(f, bg=C["panel"])
        row.pack(fill="x", pady=(6, 16))
        tk.Label(row, text=opt, bg=C["field"], fg=C["text"], font=("Consolas", 12), padx=12, pady=6).pack(side="left")

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(opt)
            cb.configure(text="✔ " + tr("copied"))
        cb = self.button(row, tr("copy"), copy, "normal")
        cb.pack(side="left", padx=8)
        btns = tk.Frame(f, bg=C["panel"])
        btns.pack(fill="x")
        self.button(btns, "▶ " + tr("run"), lambda: (win.destroy(), self.run_dota()), "accent").pack(side="right")
        self.button(btns, tr("close"), win.destroy, "normal").pack(side="right", padx=6)
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        win.geometry(f"+{max(x, 0)}+{self.root.winfo_rooty() + 120}")

    def uninstall_from_game(self):
        if not messagebox.askyesno(tr("uninstall_game"), tr("uninstall_confirm")):
            return
        try:
            removed = remove_from_dota(self.cfg, self.log)
        except Exception as e:
            messagebox.showerror(tr("error_title"), str(e))
            return
        if removed:
            messagebox.showinfo(tr("uninstall_game"), tr("uninstall_done", f=", ".join(removed)))
        else:
            messagebox.showinfo(tr("uninstall_game"), tr("uninstall_none"))

    def open_guide(self, first=False):
        win = tk.Toplevel(self.root, bg=C["panel"])
        win.title(tr("guide"))
        win.transient(self.root)
        win.resizable(False, False)
        f = tk.Frame(win, bg=C["panel"], padx=26, pady=20)
        f.pack()
        tk.Label(f, text=tr("guide_title"), bg=C["panel"], fg=C["text"], font=(FONT, 16, "bold")).pack(anchor="w")
        tk.Label(f, text=tr("guide_sub"), bg=C["panel"], fg=C["muted"], font=(FONT, 9)).pack(anchor="w", pady=(2, 12))
        opt = launch_option(self.cfg.data["lang_folder"])
        for i, (head, text) in enumerate(GUIDE_STEPS[_LANG], 1):
            row = tk.Frame(f, bg=C["panel"])
            row.pack(fill="x", pady=5)
            tk.Label(row, text=str(i), bg=C["accent"], fg="#ffffff", font=(FONT, 11, "bold"),
                     width=2).pack(side="left", anchor="n", padx=(0, 12), ipady=2)
            col = tk.Frame(row, bg=C["panel"])
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, text=head, bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold"),
                     anchor="w", justify="left").pack(fill="x")
            tk.Label(col, text=text.format(o=opt), bg=C["panel"], fg=C["muted"], font=(FONT, 9),
                     wraplength=470, anchor="w", justify="left").pack(fill="x")
        box = tk.Frame(f, bg=C["card"], padx=12, pady=10)
        box.pack(fill="x", pady=(14, 0))
        tk.Label(box, text=tr("guide_remove_h"), bg=C["card"], fg="#ff8a80", font=(FONT, 10, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(box, text=tr("guide_remove"), bg=C["card"], fg=C["muted"], font=(FONT, 9), wraplength=500,
                 anchor="w", justify="left").pack(fill="x")
        btns = tk.Frame(f, bg=C["panel"])
        btns.pack(fill="x", pady=(16, 0))

        def close():
            win.destroy()
            if first:
                self.cfg.data["guide_seen"] = True
                self.cfg.save()
                if not self.cfg.data["dota_path"] or not (Path(self.cfg.data["dota_path"]) / "game" / "dota").exists():
                    self.open_settings()
        self.button(btns, tr("guide_ok") if first else tr("close"), close, "accent").pack(side="right")
        win.protocol("WM_DELETE_WINDOW", close)
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        win.geometry(f"+{max(x, 0)}+{max(self.root.winfo_rooty() + 40, 0)}")

    def run_dota(self):
        webbrowser.open("steam://rungameid/570")


def main():
    try:
        set_lang(json.loads(CONFIG_FILE.read_text("utf-8")).get("ui_lang", "ru"))
    except Exception:
        pass
    if tk is None:
        print(tr("need_tk"))
        sys.exit(1)
    root = tk.Tk()
    try:  # иконка окна (рядом со скриптом или внутри .exe)
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        if (base / "icon.ico").exists() and sys.platform.startswith("win"):
            root.iconbitmap(default=str(base / "icon.ico"))
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
