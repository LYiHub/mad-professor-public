from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, 
                           QMenu, QLabel)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QAction

class SettingsBar(QWidget):
    """设置栏组件 - 处理所有设置相关的功能"""
    
    # 定义信号
    tts_toggled = pyqtSignal(bool)  # TTS开关信号
    language_toggled = pyqtSignal()  # 语言切换信号
    md_processor_toggled = pyqtSignal(bool)  # MarkdownProcessor切换信号
    
    def __init__(self, parent=None):
        """初始化设置栏"""
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        """初始化UI组件"""
        # 创建主布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        
        # 创建标题
        title_font = QFont("Source Han Sans SC", 11, QFont.Weight.Bold)
        doc_title = QLabel("论文阅读")
        doc_title.setFont(title_font)
        doc_title.setStyleSheet("color: white; font-weight: bold;")
        
        # 创建设置按钮
        settings_button = QPushButton("⚙")
        settings_button.setObjectName("settingsButton")
        settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_button.setToolTip("设置")
        
        # 创建设置菜单
        settings_menu = QMenu(settings_button)
        
        # 添加TTS开关选项
        self.tts_action = QAction("启用TTS语音", settings_menu, checkable=True)
        self.tts_action.setChecked(True)  # 默认启用
        self.tts_action.triggered.connect(self._on_tts_toggle)
        settings_menu.addAction(self.tts_action)
        
        # 添加MarkdownProcessor切换选项
        self.md_processor_action = QAction("正在使用论文格式处理器(原生) 点击切换为任意格式", settings_menu, checkable=True)
        self.md_processor_action.setChecked(False)  # 默认使用普通处理器
        self.md_processor_action.triggered.connect(self._on_md_processor_toggle)
        settings_menu.addAction(self.md_processor_action)
        
        # 将菜单关联到按钮
        settings_button.clicked.connect(
            lambda: settings_menu.exec(settings_button.mapToGlobal(settings_button.rect().bottomLeft()))
        )
        
        # 创建语言切换按钮
        self.lang_button = QPushButton("切换为英文")
        self.lang_button.setObjectName("langButton")
        self.lang_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_button.clicked.connect(self._on_language_toggle)
        
        # 添加到布局
        layout.addWidget(doc_title, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        layout.addWidget(settings_button)
        layout.addWidget(self.lang_button)
        
        # 设置样式
        self.setStyleSheet("""
            #settingsButton {
                background-color: transparent;
                color: white;
                border: none;
                padding: 5px;
                font-size: 16px;
            }
            
            #settingsButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
            
            #langButton {
                background-color: rgba(255, 255, 255, 0.2);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 8px;
                padding: 5px 15px;
                font-weight: bold;
            }
            
            #langButton:hover {
                background-color: rgba(255, 255, 255, 0.3);
            }
            
            QMenu {
                background-color: #FFFFFF;
                border: 1px solid #CFD8DC;
                border-radius: 4px;
                padding: 5px;
            }
            
            QMenu::item {
                padding: 5px 20px;
                border-radius: 2px;
            }
            
            QMenu::item:selected {
                background-color: #E8EAF6;
            }
            
            QMenu::separator {
                height: 1px;
                background-color: #CFD8DC;
                margin: 5px 0px;
            }
        """)
        
    def _on_tts_toggle(self, checked):
        """处理TTS开关切换"""
        self.tts_toggled.emit(checked)
    
    def _on_md_processor_toggle(self, checked):
        """处理MarkdownProcessor切换"""
        self.md_processor_toggled.emit(checked)
        
    def _on_language_toggle(self):
        """处理语言切换"""
        self.language_toggled.emit()
        
    def update_language_button(self, is_chinese):
        """更新语言按钮状态"""
        if is_chinese:
            self.lang_button.setText("切换为英文")
            self.lang_button.setStyleSheet("""
                #langButton {
                    background-color: rgba(255, 255, 255, 0.2);
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 0.3);
                    border-radius: 8px;
                    padding: 5px 15px;
                    font-weight: bold;
                }
                #langButton:hover {
                    background-color: rgba(255, 255, 255, 0.3);
                }
            """)
        else:
            self.lang_button.setText("切换为中文")
            self.lang_button.setStyleSheet("""
                #langButton {
                    background-color: rgba(65, 105, 225, 0.3);
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 0.3);
                    border-radius: 8px;
                    padding: 5px 15px;
                    font-weight: bold;
                }
                #langButton:hover {
                    background-color: rgba(65, 105, 225, 0.4);
                }
            """)
            
    def update_md_processor_status(self, is_slides_processor):
        """更新MarkdownProcessor状态"""
        if is_slides_processor:
            self.md_processor_action.setText("正在使用任意格式处理器 点击切换为原生")
        else:
            self.md_processor_action.setText("正在使用论文格式处理器(原生) 点击切换为任意格式")
        self.md_processor_action.setChecked(is_slides_processor) 