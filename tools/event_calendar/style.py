"""Notebook palette and system-font selection only; no personal state."""
from pathlib import Path
from PIL import ImageFont

MONTHS = ['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь']
GENITIVE = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
BG = '#fcfcf7'
INK = '#23475b'
MUTED = '#7e9196'
ROSE = '#c0756c'
LINE = '#d6e5e8'
HIGHLIGHT = '#f3df9f'


def font(size, bold=False, serif=False, italic=False):
    base = Path('/usr/share/fonts/truetype/dejavu')
    family = 'DejaVuSerif' if serif else 'DejaVuSans'
    suffix = '-Bold' if bold else ('-Italic' if italic and serif else '')
    path = base / (family + suffix + '.ttf')
    if serif and italic and not path.exists():
        path = Path('/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf')
    return ImageFont.truetype(str(path), size)
