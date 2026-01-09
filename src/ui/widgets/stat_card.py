"""
Statistics Card Widget
"""
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt


class StatCard(QFrame):
    """Card widget for displaying statistics"""
    
    def __init__(self, title: str, value: str = "0", 
                 subtitle: str = "", icon: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(200)
        self.setMinimumHeight(120)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header with icon and title
        header_layout = QHBoxLayout()
        
        if icon:
            icon_label = QLabel(icon)
            icon_label.setStyleSheet("font-size: 24px;")
            header_layout.addWidget(icon_label)
        
        title_label = QLabel(title)
        title_label.setObjectName("statLabel")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # Value
        self.value_label = QLabel(value)
        self.value_label.setObjectName("statValue")
        layout.addWidget(self.value_label)
        
        # Subtitle
        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setObjectName("subHeaderLabel")
            layout.addWidget(self.subtitle_label)
        else:
            self.subtitle_label = None
        
        layout.addStretch()
    
    def set_value(self, value: str):
        """Update the displayed value"""
        self.value_label.setText(value)
    
    def set_subtitle(self, subtitle: str):
        """Update the subtitle"""
        if self.subtitle_label:
            self.subtitle_label.setText(subtitle)


class StatCardRow(QFrame):
    """Row of stat cards"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(16)
        self.cards = {}
    
    def add_card(self, key: str, title: str, value: str = "0", 
                 subtitle: str = "", icon: str = "") -> StatCard:
        """Add a stat card"""
        card = StatCard(title, value, subtitle, icon)
        self.cards[key] = card
        self.layout.addWidget(card)
        return card
    
    def update_card(self, key: str, value: str, subtitle: str = None):
        """Update a card's value"""
        if key in self.cards:
            self.cards[key].set_value(value)
            if subtitle is not None:
                self.cards[key].set_subtitle(subtitle)
    
    def add_stretch(self):
        """Add stretch at end"""
        self.layout.addStretch()