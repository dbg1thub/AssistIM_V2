from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timedelta


def _install_qt_stubs() -> None:
    qtcore = types.ModuleType('PySide6.QtCore')

    class _DummyQLocale:
        class Language:
            Chinese = 'Chinese'
            English = 'English'
            Korean = 'Korean'

        class Country:
            China = 'China'
            UnitedStates = 'UnitedStates'
            SouthKorea = 'SouthKorea'

        _default = None

        def __init__(self, language=None, country=None):
            self._language = language or self.Language.English
            self._country = country or self.Country.UnitedStates

        @classmethod
        def system(cls):
            return cls(cls.Language.English, cls.Country.UnitedStates)

        @classmethod
        def setDefault(cls, locale):
            cls._default = locale

        def language(self):
            return self._language

        def name(self):
            if self._language == self.Language.Chinese:
                return 'zh_CN'
            if self._language == self.Language.Korean:
                return 'ko_KR'
            return 'en_US'

        def toString(self, value, fmt=None):
            return str(value)

    class _DummyQObject:
        def __init__(self, *args, **kwargs):
            pass

    class _DummySignalInstance:
        def __init__(self):
            self._callbacks = []
            self.events = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs):
            self.events.append((args, kwargs))
            for callback in list(self._callbacks):
                callback(*args, **kwargs)

    def _DummySignal(*args, **kwargs):
        return _DummySignalInstance()

    def _DummySlot(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    class _DummyQTimer:
        def __init__(self, *args, **kwargs):
            self.timeout = _DummySignalInstance()

        def setInterval(self, interval):
            self._interval = interval

        def start(self):
            return None

    class _DummyQCoreApplication:
        @staticmethod
        def instance():
            return None

    class _DummyQThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            return None

    class _DummyQUrl:
        def __init__(self, value=''):
            self.value = value

        @staticmethod
        def fromLocalFile(value):
            return _DummyQUrl(value)

    class _DummyQSize:
        def __init__(self, width=0, height=0):
            if hasattr(width, 'width') and hasattr(width, 'height') and height == 0:
                self._width = int(width.width())
                self._height = int(width.height())
            else:
                self._width = int(width)
                self._height = int(height)

        def width(self):
            return self._width

        def height(self):
            return self._height

        def isEmpty(self):
            return self._width <= 0 or self._height <= 0

    class _DummyQPoint:
        def __init__(self, x=0, y=0):
            self._x = int(x)
            self._y = int(y)

        def x(self):
            return self._x

        def y(self):
            return self._y

    class _DummyQRect:
        def __init__(self, x=0, y=0, width=0, height=0):
            if hasattr(x, 'x') and hasattr(x, 'y') and hasattr(x, 'width') and hasattr(x, 'height') and y == 0 and width == 0 and height == 0:
                self._x = int(x.x())
                self._y = int(x.y())
                self._width = int(x.width())
                self._height = int(x.height())
            else:
                self._x = int(x)
                self._y = int(y)
                self._width = int(width)
                self._height = int(height)

        def x(self):
            return self._x

        def y(self):
            return self._y

        def width(self):
            return self._width

        def height(self):
            return self._height

        def left(self):
            return self._x

        def top(self):
            return self._y

        def right(self):
            return self._x + self._width - 1

        def bottom(self):
            return self._y + self._height - 1

        def size(self):
            return _DummyQSize(self._width, self._height)

        def adjusted(self, left, top, right, bottom):
            return _DummyQRect(
                self._x + int(left),
                self._y + int(top),
                self._width - int(left) + int(right),
                self._height - int(top) + int(bottom),
            )

    class _DummyQRectF(_DummyQRect):
        pass

    class _DummyModelIndex:
        def __init__(self, row: int = -1, column: int = 0):
            self._row = row
            self._column = column

        def isValid(self):
            return self._row >= 0

        def row(self):
            return self._row

        def column(self):
            return self._column

    class _DummyAlignmentFlag:
        AlignCenter = 1
        AlignRight = 2
        AlignLeft = 4
        AlignVCenter = 8
        AlignTop = 16

    class _DummyItemDataRole:
        DisplayRole = 0
        TextAlignmentRole = 1
        SizeHintRole = 2
        UserRole = 1000

    class _DummyTextElideMode:
        ElideRight = 1

    class _DummyAspectRatioMode:
        KeepAspectRatio = 1

    class _DummyTransformationMode:
        SmoothTransformation = 1

    class _DummyGlobalColor:
        white = 'white'
        transparent = 'transparent'

    class _DummyQt:
        ItemDataRole = _DummyItemDataRole
        AlignmentFlag = _DummyAlignmentFlag
        TextElideMode = _DummyTextElideMode
        AspectRatioMode = _DummyAspectRatioMode
        TransformationMode = _DummyTransformationMode
        GlobalColor = _DummyGlobalColor

    class _DummyAbstractListModel:
        def __init__(self, *args, **kwargs):
            self.dataChanged = _DummySignalInstance()
            self.layoutAboutToBeChanged = _DummySignalInstance()
            self.layoutChanged = _DummySignalInstance()
            self._qt_ops = []

        def beginInsertRows(self, parent, first, last):
            self._qt_ops.append(('insert', first, last))

        def endInsertRows(self):
            self._qt_ops.append(('insert_end',))

        def beginRemoveRows(self, parent, first, last):
            self._qt_ops.append(('remove', first, last))

        def endRemoveRows(self):
            self._qt_ops.append(('remove_end',))

        def beginResetModel(self):
            self._qt_ops.append(('reset_begin',))

        def endResetModel(self):
            self._qt_ops.append(('reset_end',))

        def beginMoveRows(self, source_parent, start, end, destination_parent, destination):
            self._qt_ops.append(('move', start, end, destination))

        def endMoveRows(self):
            self._qt_ops.append(('move_end',))

        def index(self, row, column=0, parent=None):
            return _DummyModelIndex(row, column)

    qtcore.QLocale = _DummyQLocale
    qtcore.QObject = _DummyQObject
    qtcore.Signal = _DummySignal
    qtcore.Slot = _DummySlot
    qtcore.QTimer = _DummyQTimer
    qtcore.QCoreApplication = _DummyQCoreApplication
    qtcore.QThread = _DummyQThread
    qtcore.QUrl = _DummyQUrl
    qtcore.QSize = _DummyQSize
    qtcore.QPoint = _DummyQPoint
    qtcore.QRect = _DummyQRect
    qtcore.QRectF = _DummyQRectF
    qtcore.QModelIndex = _DummyModelIndex
    qtcore.QAbstractListModel = _DummyAbstractListModel
    qtcore.Qt = _DummyQt

    qtgui = types.ModuleType('PySide6.QtGui')

    class _DummyQColor:
        def __init__(self, *args, **kwargs):
            self.args = args

    class _DummyQFont:
        class SpacingType:
            AbsoluteSpacing = 0

        def __init__(self, *args, **kwargs):
            self._pixel_size = 12
            self._bold = False

        def setPixelSize(self, value):
            self._pixel_size = int(value)

        def pixelSize(self):
            return self._pixel_size

        def setBold(self, value):
            self._bold = bool(value)

        def setFamilies(self, families):
            self._families = list(families)

        def setFamily(self, family):
            self._family = family

        def setLetterSpacing(self, *args, **kwargs):
            return None

    class _DummyQFontMetrics:
        def __init__(self, font=None):
            self._font = font or _DummyQFont()

        def height(self):
            return max(1, int(getattr(self._font, '_pixel_size', 12) * 1.25))

        def ascent(self):
            return max(1, int(self.height() * 0.8))

        def descent(self):
            return max(0, self.height() - self.ascent())

        def horizontalAdvance(self, text):
            return max(0, len(str(text or '')) * max(1, int(getattr(self._font, '_pixel_size', 12) * 0.55)))

        def elidedText(self, text, mode, width):
            text = str(text or '')
            if self.horizontalAdvance(text) <= width:
                return text
            char_width = max(1, self.horizontalAdvance('M'))
            max_chars = max(0, int(width) // char_width - 1)
            return text[:max_chars] + ('...' if max_chars else '')

    class _DummyQPixmap:
        def __init__(self, *args, **kwargs):
            self._width = 0
            self._height = 0

        def isNull(self):
            return self._width <= 0 or self._height <= 0

        def width(self):
            return self._width

        def height(self):
            return self._height

        def size(self):
            return _DummyQSize(self._width, self._height)

        def scaled(self, width, height, *args, **kwargs):
            pixmap = _DummyQPixmap()
            pixmap._width = int(width)
            pixmap._height = int(height)
            return pixmap

        def fill(self, *args, **kwargs):
            return None

        def loadFromData(self, payload):
            return bool(payload)

        def save(self, path):
            return True

        @staticmethod
        def fromImage(image):
            return _DummyQPixmap()

    class _DummyPainter:
        class RenderHint:
            Antialiasing = 1

        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return None
            return _noop

    class _DummyQImageReader:
        def __init__(self, *args, **kwargs):
            pass

        def setScaledSize(self, *args, **kwargs):
            return None

        def read(self):
            return None

    qtgui.QColor = _DummyQColor
    qtgui.QFont = _DummyQFont
    qtgui.QFontMetrics = _DummyQFontMetrics
    qtgui.QPainter = _DummyPainter
    qtgui.QPainterPath = type('QPainterPath', (), {})
    qtgui.QPen = type('QPen', (), {'__init__': lambda self, *args, **kwargs: None})
    qtgui.QPixmap = _DummyQPixmap
    qtgui.QImageReader = _DummyQImageReader
    qtgui.QIcon = type('QIcon', (), {'__init__': lambda self, *args, **kwargs: None})
    qtgui.QIconEngine = type('QIconEngine', (), {'__init__': lambda self, *args, **kwargs: None})

    qtwidgets = types.ModuleType('PySide6.QtWidgets')

    class _DummyQApplication:
        _instance = None

        def __init__(self, *args, **kwargs):
            _DummyQApplication._instance = self

        @staticmethod
        def instance():
            return _DummyQApplication._instance

    qtwidgets.QApplication = _DummyQApplication
    qtwidgets.QStyledItemDelegate = type('QStyledItemDelegate', (), {'__init__': lambda self, *args, **kwargs: None})
    qtwidgets.QStyleOptionViewItem = type('QStyleOptionViewItem', (), {})
    qtwidgets.QStyle = type(
        'QStyle',
        (),
        {'StateFlag': type('StateFlag', (), {'State_Selected': 1, 'State_MouseOver': 2})},
    )

    qtnetwork = types.ModuleType('PySide6.QtNetwork')

    class _DummyQNetworkAccessManager:
        def __init__(self, *args, **kwargs):
            self.finished = _DummySignalInstance()

        def get(self, request):
            return types.SimpleNamespace(finished=_DummySignalInstance())

    qtnetwork.QNetworkAccessManager = _DummyQNetworkAccessManager
    qtnetwork.QNetworkRequest = type('QNetworkRequest', (), {'__init__': lambda self, *args, **kwargs: None})
    qtnetwork.QNetworkReply = type(
        'QNetworkReply',
        (),
        {'NetworkError': type('NetworkError', (), {'NoError': 0})},
    )

    pyside = types.ModuleType('PySide6')
    pyside.QtCore = qtcore
    pyside.QtGui = qtgui
    pyside.QtWidgets = qtwidgets
    pyside.QtNetwork = qtnetwork
    sys.modules['PySide6'] = pyside
    sys.modules['PySide6.QtCore'] = qtcore
    sys.modules['PySide6.QtGui'] = qtgui
    sys.modules['PySide6.QtWidgets'] = qtwidgets
    sys.modules['PySide6.QtNetwork'] = qtnetwork


_install_qt_stubs()

from client.models.message import ChatMessage, MessageStatus, Session
from client.models import message_model as message_model_module
from client.models import session_model as session_model_module

message_model_module = importlib.reload(message_model_module)
session_model_module = importlib.reload(session_model_module)

MessageModel = message_model_module.MessageModel
SessionModel = session_model_module.SessionModel


BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)


def _message(message_id: str, minutes: int) -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        session_id='session-1',
        sender_id='alice',
        content=message_id,
        status=MessageStatus.SENT,
        is_self=True,
        timestamp=BASE_TIME + timedelta(minutes=minutes),
    )


def _session(session_id: str, minutes: int) -> Session:
    return Session(
        session_id=session_id,
        name=session_id,
        last_message=session_id,
        last_message_time=BASE_TIME + timedelta(minutes=minutes),
        extra={},
    )


def test_message_model_add_messages_uses_incremental_insert() -> None:
    model = MessageModel()

    model.add_messages([_message('m-1', 0), _message('m-2', 10)])

    assert ('reset_begin',) not in model._qt_ops
    assert ('insert', 0, 3) in model._qt_ops
    assert model.rowCount() == 4
    assert model.data(model.index(0, 0), model.DisplayKindRole) == model.DISPLAY_TIME_SEPARATOR
    assert model.data(model.index(2, 0), model.DisplayKindRole) == model.DISPLAY_TIME_SEPARATOR

    model._qt_ops.clear()
    model.add_message(_message('m-3', 11))

    assert ('reset_begin',) not in model._qt_ops
    assert ('insert', 4, 4) in model._qt_ops
    assert model.rowCount() == 5



def test_message_model_prepend_messages_uses_incremental_insert() -> None:
    model = MessageModel()
    model.add_messages([_message('m-2', 10), _message('m-3', 11)])

    model._qt_ops.clear()
    model.prepend_messages([_message('m-1', 0)])

    assert ('reset_begin',) not in model._qt_ops
    assert ('insert', 0, 1) in model._qt_ops
    assert model.rowCount() == 5
    assert model.data(model.index(0, 0), model.DisplayKindRole) == model.DISPLAY_TIME_SEPARATOR
    assert model.data(model.index(2, 0), model.DisplayKindRole) == model.DISPLAY_TIME_SEPARATOR



def test_session_model_add_session_upserts_existing_session_id() -> None:
    model = SessionModel()
    original = _session('s-1', 0)
    replacement = _session('s-1', 15)
    replacement.last_message = 'replacement'

    model.add_session(original)
    model._qt_ops.clear()
    model.dataChanged.events.clear()
    model.add_session(replacement)

    assert model.rowCount() == 1
    assert ('insert', 0, 0) not in model._qt_ops
    assert model.get_session(0).last_message == 'replacement'
    assert model.get_session(0).last_message_time == replacement.last_message_time
    assert model.dataChanged.events


def test_message_model_refresh_recalled_message_without_full_reset() -> None:
    model = MessageModel()
    message = _message('m-1', 0)
    model.add_message(message)

    model._qt_ops.clear()
    model.dataChanged.events.clear()
    message.status = MessageStatus.RECALLED
    message.extra['recall_notice'] = 'recalled'
    model.refresh_message('m-1')

    assert ('reset_begin',) not in model._qt_ops
    assert model.data(model.index(0, 0), model.DisplayKindRole) == model.DISPLAY_TIME_SEPARATOR
    assert model.data(model.index(1, 0), model.DisplayKindRole) == model.DISPLAY_RECALL_NOTICE
    assert model.dataChanged.events


def test_message_model_replace_message_updates_visible_message_payload() -> None:
    model = MessageModel()
    original = _message('m-1', 0)
    model.add_message(original)

    replacement = _message('m-1', 0)
    replacement.content = '/uploads/encrypted.bin'
    replacement.extra = {'local_path': r'C:\Temp\plain-image.jpg'}

    model.replace_message(replacement)

    display_item = model.data(model.index(1, 0), model.MessageRole)
    assert display_item['local_path'] == r'C:\Temp\plain-image.jpg'
    assert display_item['content'] == '/uploads/encrypted.bin'





def test_message_model_time_separator_uses_newer_message_timestamp() -> None:
    model = MessageModel()

    model.add_messages([_message('m-1', 0), _message('m-2', 10)])

    separator_timestamp = model.data(model.index(2, 0), model.TimestampRole)

    assert separator_timestamp == BASE_TIME + timedelta(minutes=10)


def test_message_model_add_message_reorders_out_of_order_insert() -> None:
    model = MessageModel()
    model.add_messages([_message('m-2', 10)])

    model.add_message(_message('m-1', 0))

    assert [message.message_id for message in model.get_messages()] == ['m-1', 'm-2']
    assert model.data(model.index(0, 0), model.DisplayKindRole) == model.DISPLAY_TIME_SEPARATOR
    assert model.data(model.index(2, 0), model.DisplayKindRole) == model.DISPLAY_TIME_SEPARATOR


def test_message_model_refresh_message_reorders_when_timestamp_changes() -> None:
    model = MessageModel()
    first = _message('m-1', 0)
    second = _message('m-2', 10)
    model.add_messages([first, second])

    first.timestamp = BASE_TIME + timedelta(minutes=15)
    model.refresh_message('m-1', allow_reorder=True)

    assert [message.message_id for message in model.get_messages()] == ['m-2', 'm-1']


def test_message_model_toggle_time_separator_expanded_updates_role() -> None:
    model = MessageModel()
    model.add_messages([_message('m-1', 0)])

    assert model.data(model.index(0, 0), model.TimeExpandedRole) is False

    assert model.toggle_time_separator_expanded('m-1') is True
    assert model.data(model.index(0, 0), model.TimeExpandedRole) is True


def test_message_model_prepend_same_group_keeps_single_leading_separator() -> None:
    model = MessageModel()
    model.add_messages([_message('m-2', 10), _message('m-3', 11)])

    model.prepend_messages([_message('m-1', 9)])

    display_kinds = [model.data(model.index(row, 0), model.DisplayKindRole) for row in range(model.rowCount())]
    assert display_kinds == [model.DISPLAY_TIME_SEPARATOR, model.DISPLAY_MESSAGE, model.DISPLAY_MESSAGE, model.DISPLAY_MESSAGE]


def test_session_model_initial_load_uses_insert_and_update_moves_row() -> None:
    model = SessionModel()
    newer = _session('s-new', 5)
    older = _session('s-old', 0)

    model.set_sessions([older, newer])

    assert ('reset_begin',) not in model._qt_ops
    assert ('insert', 0, 1) in model._qt_ops
    assert model.get_session(0).session_id == 's-new'

    model._qt_ops.clear()
    model.dataChanged.events.clear()
    model.update_session('s-old', last_message='promoted', last_message_time=BASE_TIME + timedelta(minutes=10))

    assert ('reset_begin',) not in model._qt_ops
    assert ('move', 1, 1, 0) in model._qt_ops
    assert model.get_session(0).session_id == 's-old'
    assert model.dataChanged.events
