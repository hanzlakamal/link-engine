"""
Dashboard Tab - Overview and Statistics
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QFrame, QScrollArea, QGridLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtCharts import QChart, QChartView, QPieSeries, QLineSeries, QValueAxis

from config import Settings
from core.database import Database
from core.logger import ui_logger
from ui.widgets.stat_card import StatCard, StatCardRow
from PyQt6.QtGui import QPainter



class DashboardTab(QWidget):
    """Dashboard with overview statistics"""
    
    def __init__(self, settings: Settings, db: Database, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db = db
        
        self.setup_ui()
        self.refresh()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Header
        header = QLabel("Dashboard Overview")
        header.setObjectName("headerLabel")
        layout.addWidget(header)
        
        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(20)
        
        # Stats cards row 1
        self.stats_row1 = StatCardRow()
        self.stats_row1.add_card("total_domains", "Total Domains", "0", "", "🌐")
        self.stats_row1.add_card("analyzed", "Analyzed", "0", "", "🔬")
        self.stats_row1.add_card("contacted", "Contacted", "0", "", "📧")
        self.stats_row1.add_card("live_links", "Live Links", "0", "", "🔗")
        self.stats_row1.add_stretch()
        content_layout.addWidget(self.stats_row1)
        
        # Stats cards row 2
        self.stats_row2 = StatCardRow()
        self.stats_row2.add_card("avg_dr", "Avg. DR", "0", "", "📊")
        self.stats_row2.add_card("response_rate", "Response Rate", "0%", "", "📬")
        self.stats_row2.add_card("success_rate", "Success Rate", "0%", "", "✅")
        self.stats_row2.add_card("pending", "Pending Actions", "0", "", "⏳")
        self.stats_row2.add_stretch()
        content_layout.addWidget(self.stats_row2)
        
        # Charts row
        charts_layout = QHBoxLayout()
        
        # Status distribution pie chart
        self.status_chart = self.create_status_chart()
        charts_layout.addWidget(self.status_chart)
        
        # Activity timeline (placeholder)
        activity_frame = QFrame()
        activity_frame.setObjectName("card")
        activity_layout = QVBoxLayout(activity_frame)
        activity_layout.addWidget(QLabel("📈 Recent Activity"))
        self.activity_list = QLabel("No recent activity")
        self.activity_list.setWordWrap(True)
        self.activity_list.setStyleSheet("color: #8892b0;")
        activity_layout.addWidget(self.activity_list)
        activity_layout.addStretch()
        charts_layout.addWidget(activity_frame)
        
        content_layout.addLayout(charts_layout)
        
        # Quick actions
        actions_frame = QFrame()
        actions_frame.setObjectName("card")
        actions_layout = QVBoxLayout(actions_frame)
        actions_layout.addWidget(QLabel("⚡ Quick Actions"))
        
        quick_actions = QHBoxLayout()
        
        from PyQt6.QtWidgets import QPushButton
        
        import_btn = QPushButton("📥 Import Domains")
        import_btn.setObjectName("primaryButton")
        quick_actions.addWidget(import_btn)
        
        analyze_btn = QPushButton("🔬 Analyze Pending")
        quick_actions.addWidget(analyze_btn)
        
        outreach_btn = QPushButton("📧 Start Outreach")
        outreach_btn.setObjectName("successButton")
        quick_actions.addWidget(outreach_btn)
        
        quick_actions.addStretch()
        actions_layout.addLayout(quick_actions)
        
        content_layout.addWidget(actions_frame)
        content_layout.addStretch()
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
    
    def create_status_chart(self) -> QChartView:
        """Create status distribution pie chart"""
        series = QPieSeries()
        series.append("Pending", 1)
        series.append("Analyzed", 1)
        series.append("Contacted", 1)
        
        # Store reference for updates
        self.pie_series = series
        
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Domain Status Distribution")
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setBackgroundBrush(Qt.GlobalColor.transparent)
        chart.setTitleBrush(Qt.GlobalColor.white)
        chart.legend().setLabelColor(Qt.GlobalColor.white)
        
        chart_view = QChartView(chart)
        #chart_view.setRenderHint(chart_view.RenderHint.Antialiasing)
        chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart_view.setMinimumHeight(300)
        chart_view.setStyleSheet("background: transparent;")
        
        return chart_view
    
    def refresh(self):
        """Refresh dashboard data"""
        ui_logger.debug("Refreshing dashboard")
        
        try:
            # Get domain stats
            stats = self.db.get_domain_stats()
            
            self.stats_row1.update_card("total_domains", str(stats['total']))
            self.stats_row1.update_card("analyzed", str(stats['by_status'].get('analyzed', 0)))
            self.stats_row1.update_card("contacted", str(stats['by_status'].get('contacted', 0)))
            
            # Get link stats
            link_stats = self.db.get_backlink_stats()
            self.stats_row1.update_card("live_links", str(link_stats['total_live']))
            
            # Row 2 stats
            self.stats_row2.update_card("avg_dr", str(stats['avg_dr']))
            self.stats_row2.update_card("pending", str(stats['by_status'].get('pending', 0)))
            
            # Update pie chart
            self.update_status_chart(stats['by_status'])
            
            # Update activity
            self.update_activity()
            
        except Exception as e:
            ui_logger.error(f"Dashboard refresh failed: {e}")
    
    def update_status_chart(self, status_data: dict):
        """Update the pie chart with new data"""
        self.pie_series.clear()
        
        colors = {
            'pending': '#f39c12',
            'analyzed': '#3498db',
            'contacted': '#9b59b6',
            'responded': '#2ecc71',
            'published': '#00b894',
            'rejected': '#e74c3c'
        }
        
        for status, count in status_data.items():
            if count > 0:
                slice = self.pie_series.append(status.title(), count)
                if status in colors:
                    slice.setBrush(Qt.GlobalColor.white)  # Will be styled
    
    def update_activity(self):
        """Update recent activity list"""
        activities = self.db.get_activity_log(limit=10)
        
        if activities:
            lines = []
            for act in activities[:5]:
                time_str = act['timestamp'][:16] if act['timestamp'] else "Unknown"
                lines.append(f"• {time_str} - {act['description']}")
            
            self.activity_list.setText("\n".join(lines))
        else:
            self.activity_list.setText("No recent activity")