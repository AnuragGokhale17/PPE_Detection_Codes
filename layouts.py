# layouts.py

import dash_bootstrap_components as dbc #type: ignore
from dash import dcc, html #type: ignore


# --- SHARED STYLES DICTIONARY ---
auth_page_style = {
    'backgroundImage': "url('/assets/bg3.png')",
    'backgroundSize': 'cover',
    'backgroundPosition': 'center',
    'backgroundAttachment': 'fixed',
    'minHeight': '100vh',
    'display': 'flex',
    'alignItems': 'center',
    'justifyContent': 'center',
    'position': 'relative',
}

form_card_style = {
    "width": "100%",
    "maxWidth": "550px",
    "padding": "2.5rem",
    "background": "rgba(255, 255, 255, 0.95)",
    "backdropFilter": "blur(20px)",
    "borderRadius": "20px",
    "border": "1px solid rgba(255, 255, 255, 0.3)",
    "boxShadow": "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
}


def create_dashboard_selection_layout():
    return html.Div([
        # Background overlay for better contrast
        html.Div(className="bg-overlay"),
        
        dbc.Container([
            # Header Section with Animation
            html.Div([
                html.Div([
                    html.H1("Industrial Safety", className="main-title"),
                    html.H2("Dashboard Hub", className="sub-title"),
                    html.P("Intelligent monitoring and analytics for workplace safety", className="tagline"),
                ], className="header-content fade-in-up"),
            ], className="header-section"),

            # Dashboard Cards Section
            html.Div([
                dbc.Row([
                    # PPE Monitoring Dashboard
                    dbc.Col([
                        html.A([
                            dbc.Card([
                                html.Div([
                                    html.Div([
                                        html.I(className="fas fa-hard-hat card-icon"),
                                    ], className="icon-container"),
                                    html.H3("PPE Monitoring", className="card-title"),
                                    html.P("Real-time safety compliance tracking with instant violation alerts and comprehensive reporting", className="card-desc"),
                                    html.Div([
                                        html.Span("Live Dashboard", className="feature-tag"),
                                        html.Span("Real-time", className="feature-tag"),
                                    ], className="feature-tags"),
                                    html.Div([
                                        html.I(className="fas fa-arrow-right launch-arrow"),
                                        html.Span("Launch Dashboard", className="launch-text")
                                    ], className="launch-button")
                                ], className="card-content")
                            ], className="dashboard-card ppe-card")
                        ], href="/", className="card-link"),
                    ], lg=6, md=6, sm=12, className="card-col fade-in-left"),

                    # Analytics Dashboard
                    dbc.Col([
                        html.A([
                            dbc.Card([
                                html.Div([
                                    html.Div([
                                        html.I(className="fas fa-chart-line card-icon"),
                                    ], className="icon-container"),
                                    html.H3("Violation Analytics", className="card-title"),
                                    html.P("Advanced data insights and predictive analytics for safety trends and pattern recognition", className="card-desc"),
                                    html.Div([
                                        html.Span("AI Powered", className="feature-tag"),
                                        html.Span("Insights", className="feature-tag"),
                                    ], className="feature-tags"),
                                    html.Div([
                                        html.I(className="fas fa-arrow-right launch-arrow"),
                                        html.Span("View Analytics", className="launch-text")
                                    ], className="launch-button")
                                ], className="card-content")
                            ], className="dashboard-card analytics-card")
                        ], id='analytics-card-link', className="card-link"), # <-- THIS IS THE MODIFIED LINE
                    ], lg=6, md=6, sm=12, className="card-col fade-in-right"),
                ], className="cards-row", justify="center"),
            ], className="cards-section"),

            # Footer Section
            html.Div([
                html.P("Powered by IIoT Team | Solar Industries India Ltd.", className="footer-text"),
            ], className="footer-section fade-in-up"),

        ], fluid=True, className="main-container")
    ], className="dashboard-wrapper")


def create_login_layout():
    """Modern login layout with enhanced UX and animations."""
    return html.Div([
        # Animated background overlay
        html.Div(className="auth-bg-overlay"),
        
        html.Div([
            # Logo section
            html.Div([
                html.Img(src="/assets/logo.png", className="auth-logo fade-in-down"),
                html.H1("Industrial Safety", className="auth-brand-title fade-in-down"),
                html.P("Secure Access Portal", className="auth-brand-subtitle fade-in-down"),
            ], className="auth-brand-section"),
            
            # Login form
            html.Div([
                html.H2("Welcome Back", className="auth-form-title"),
                html.P("Sign in to your account", className="auth-form-subtitle"),
                
                # Email input with icon
                html.Div([
                    html.I(className="fas fa-envelope input-icon"),
                    dbc.Input(
                        id="login-email", 
                        type="email", 
                        placeholder="Enter your email",
                        className="modern-input"
                    ),
                ], className="input-group"),
                            
                # --- START: CORRECTED PASSWORD INPUT ---
                # This now has the EXACT same structure as the email input above.
                html.Div(
                    className="input-group",
                    children=[
                        # The lock icon
                        html.I(className="fas fa-lock input-icon"),
                        
                        # The input field (using the same 'modern-input' class)
                        dbc.Input(
                            id="login-password",
                            type="password",
                            placeholder="Enter your password",
                            className="modern-input"
                        ),
                        
                        # The eye-toggle button (will be positioned with CSS)
                        dbc.Button(
                            html.I(className="fas fa-eye", id="password-toggle-icon"),
                            id="password-toggle-btn",
                            className="password-toggle"
                        ),
                    ]
                ),
                # --- END: CORRECTED PASSWORD INPUT ---

                # Login button with loading state
                dcc.Loading([
                    dbc.Button(
                        [
                            html.Span("Sign In", className="btn-text"),
                            html.I(className="fas fa-arrow-right btn-icon"),
                        ],
                        id="login-button", 
                        className="modern-btn primary-btn w-100"
                    )
                ], type="circle", color="#2563eb"),
                
                # Alert container
                html.Div(id="login-alert", className="alert-container"),
                
                # Footer links
                html.Div([
                    dcc.Link("Forgot your password?", href="/forgot-password", className="auth-link"),
                ], className="auth-footer"),
                
            ], className="auth-form fade-in-up"),
            
        ], className="auth-card", style=form_card_style),
    ], className="auth-page", style=auth_page_style)


def create_otp_layout():
    """Modern OTP verification layout."""
    return html.Div([
        html.Div(className="auth-bg-overlay"),
        
        html.Div([
            # Back button
            html.Div([
                dcc.Link([
                    html.I(className="fas fa-arrow-left"),
                    html.Span("Back to Login")
                ], href="/login", className="back-link fade-in-down"),
            ], className="auth-back-section"),
            
            # OTP form
            html.Div([
                html.Div([
                    html.I(className="fas fa-shield-alt otp-icon"),
                ], className="otp-icon-container"),
                
                html.H2("Verify Your Identity", className="auth-form-title"),
                html.P("Enter the 6-digit code sent to your email", className="auth-form-subtitle"),
                
                # OTP input with special styling
                html.Div([
                    dbc.Input(
                        id="otp-input", 
                        type="text", 
                        placeholder="000000",
                        maxLength=6,
                        className="otp-input"
                    ),
                ], className="otp-input-container"),
                
                # Verify button
                dcc.Loading([
                    dbc.Button(
                        [
                            html.Span("Verify Code", className="btn-text"),
                            html.I(className="fas fa-check btn-icon"),
                        ],
                        id="otp-verify-button", 
                        className="modern-btn primary-btn w-100"
                    )
                ], type="circle", color="#2563eb"),
                
                html.Div(id="otp-alert", className="alert-container"),
                
                # Resend option
                html.Div([
                    html.Span("Didn't receive the code? "),
                    html.A("Resend", href="#", className="auth-link resend-link"),
                ], className="auth-footer"),
                
            ], className="auth-form fade-in-up"),
            
        ], className="auth-card", style=form_card_style),
    ], className="auth-page", style=auth_page_style)


def create_forgot_password_layout():
    """Modern forgot password layout."""
    return html.Div([
        html.Div(className="auth-bg-overlay"),
        
        html.Div([
            # Back button
            html.Div([
                dcc.Link([
                    html.I(className="fas fa-arrow-left"),
                    html.Span("Back to Login")
                ], href="/login", className="back-link fade-in-down"),
            ], className="auth-back-section"),
            
            # Forgot password form
            html.Div([
                html.Div([
                    html.I(className="fas fa-key forgot-icon"),
                ], className="forgot-icon-container"),
                
                html.H2("Reset Password", className="auth-form-title"),
                html.P("Enter your email and we'll send you a reset link", className="auth-form-subtitle"),
                
                # Email input
                html.Div([
                    html.I(className="fas fa-envelope input-icon"),
                    dbc.Input(
                        id="forgot-pass-email", 
                        type="email", 
                        placeholder="Enter your registered email",
                        className="modern-input"
                    ),
                ], className="input-group"),
                
                # Send button
                dcc.Loading([
                    dbc.Button(
                        [
                            html.Span("Send Reset Link", className="btn-text"),
                            html.I(className="fas fa-paper-plane btn-icon"),
                        ],
                        id="forgot-pass-button", 
                        className="modern-btn primary-btn w-100"
                    )
                ], type="circle", color="#2563eb"),
                
                html.Div(id="forgot-pass-alert", className="alert-container"),
                
            ], className="auth-form fade-in-up"),
            
        ], className="auth-card", style=form_card_style),
    ], className="auth-page", style=auth_page_style)


def create_reset_password_layout():
    """Modern password reset layout."""
    return html.Div([
        html.Div(className="auth-bg-overlay"),
        
        html.Div([
            # Reset password form
            html.Div([
                html.Div([
                    html.I(className="fas fa-lock-open reset-icon"),
                ], className="reset-icon-container"),
                
                html.H2("Create New Password", className="auth-form-title"),
                html.P("Choose a strong password for your account", className="auth-form-subtitle"),
                
                # New password input
                html.Div([
                    html.I(className="fas fa-lock input-icon"),
                    dbc.Input(
                        id="reset-pass-new", 
                        type="password", 
                        placeholder="New password",
                        className="modern-input"
                    ),
                ], className="input-group"),
                
                # Confirm password input
                html.Div([
                    html.I(className="fas fa-lock input-icon"),
                    dbc.Input(
                        id="reset-pass-confirm", 
                        type="password", 
                        placeholder="Confirm new password",
                        className="modern-input"
                    ),
                ], className="input-group"),
                
                # Reset button
                dcc.Loading([
                    dbc.Button(
                        [
                            html.Span("Update Password", className="btn-text"),
                            html.I(className="fas fa-check btn-icon"),
                        ],
                        id="reset-pass-button", 
                        className="modern-btn primary-btn w-100"
                    )
                ], type="circle", color="#2563eb"),
                
                html.Div(id="reset-pass-alert", className="alert-container"),
                
            ], className="auth-form fade-in-up"),
            
        ], className="auth-card", style=form_card_style),
    ], className="auth-page", style=auth_page_style)


def create_admin_layout(session_data):
    """Modern admin layout with enhanced UX."""
    return html.Div([
        # Background with overlay
        html.Div(className="admin-bg-overlay"),
        
        # Header matching dashboard style
        html.Div([
            dbc.Container([
                html.Div([
                    html.H1([
                        html.I(className="fas fa-users-cog me-3"),
                        "Admin Panel"
                    ], className="page-title fade-in-down"),
                    html.P("User Management & System Administration", className="page-subtitle fade-in-down"),
                ], className="page-header"),
            ], fluid=True)
        ], className="admin-header"),

        dbc.Container([
            dbc.Row([
                # Add New User Panel
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.I(className="fas fa-user-plus panel-icon"),
                            html.H3("Add New User", className="panel-title"),
                        ], className="panel-header"),
                        
                        html.Div([
                            # Email input
                            html.Div([
                                html.Label("Email Address", className="input-label"),
                                html.Div([
                                    html.I(className="fas fa-envelope input-icon"),
                                    dbc.Input(
                                        id="admin-add-email", 
                                        type="email",
                                        placeholder="user@solargroup.com", 
                                        className="modern-input"
                                    ),
                                ], className="input-group"),
                            ], className="form-field"),
                            
                            # Password input
                            html.Div([
                                html.Label("Temporary Password", className="input-label"),
                                html.Div([
                                    html.I(className="fas fa-lock input-icon"),
                                    dbc.Input(
                                        id="admin-add-password", 
                                        type="password",
                                        placeholder="Temporary password", 
                                        className="modern-input"
                                    ),
                                ], className="input-group"),
                            ], className="form-field"),
                            
                            # Role select
                            html.Div([
                                html.Label("User Role", className="input-label"),
                                html.Div([
                                    html.I(className="fas fa-user-tag input-icon"),
                                    dbc.Select(
                                        id="admin-add-role",
                                        options=[
                                            {"label": "👤 User", "value": "user"},
                                            {"label": "👑 Admin", "value": "admin"},
                                        ],
                                        value="user",
                                        className="modern-select"
                                    ),
                                ], className="input-group"),
                            ], className="form-field"),
                            
                            # Add button
                            dbc.Button(
                                [
                                    html.I(className="fas fa-plus me-2"),
                                    "Add User"
                                ],
                                id="admin-add-user-button", 
                                className="modern-btn success-btn w-100"
                            ),
                            
                            html.Div(id="admin-add-alert", className="alert-container"),
                        ], className="panel-content"),
                    ], className="admin-panel add-user-panel fade-in-left")
                ], lg=4, md=6, sm=12, className="mb-4"),

                # Existing Users Panel
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.I(className="fas fa-users panel-icon"),
                            html.H3("Existing Users", className="panel-title"),
                        ], className="panel-header"),
                        
                        html.Div([
                            # Search bar
                            html.Div([
                                html.Div([
                                    html.I(className="fas fa-search input-icon"),
                                    dbc.Input(
                                        placeholder="Search users...", 
                                        className="modern-input search-input"
                                    ),
                                ], className="input-group search-group"),
                            ], className="search-container"),
                            
                            # User table container
                            html.Div(
                                id="admin-user-table-container",
                                className="user-table-container"
                            ),
                        ], className="panel-content"),
                    ], className="admin-panel users-panel fade-in-right")
                ], lg=8, md=6, sm=12),
            ], className="admin-row"),
        ], fluid=True, className="admin-container"),

    ], className="admin-page")


def create_activity_logs_layout():
    """Modern activity logs layout."""
    return html.Div([
        # Background with overlay
        html.Div(className="logs-bg-overlay"),
        
        # Header
        html.Div([
            dbc.Container([
                html.Div([
                    html.H1([
                        html.I(className="fas fa-history me-3"),
                        "Activity Logs"
                    ], className="page-title fade-in-down"),
                    html.P("System monitoring and audit trail", className="page-subtitle fade-in-down"),
                ], className="page-header"),
            ], fluid=True)
        ], className="logs-header"),

        dbc.Container([
            # # Filter Section
            # html.Div([
            #     html.Div([
            #         html.I(className="fas fa-filter panel-icon"),
            #         html.H3("Filter Logs", className="panel-title"),
            #     ], className="panel-header"),
                
            #     dbc.Row([
            #         dbc.Col([
            #             html.Label("Date Range", className="input-label"),
            #             html.Div([
            #                 html.I(className="fas fa-calendar input-icon"),
            #                 dcc.DatePickerRange(
            #                     id="logs-date-range",
            #                     className="modern-date-picker"
            #                 ),
            #             ], className="input-group"),
            #         ], md=4),
                    
            #         dbc.Col([
            #             html.Label("Log Level", className="input-label"),
            #             html.Div([
            #                 html.I(className="fas fa-layer-group input-icon"),
            #                 dbc.Select(
            #                     options=[
            #                         {"label": "🔴 Error", "value": "error"},
            #                         {"label": "🟡 Warning", "value": "warning"},
            #                         {"label": "🔵 Info", "value": "info"},
            #                         {"label": "🟢 Success", "value": "success"},
            #                     ],
            #                     placeholder="Select level...",
            #                     className="modern-select"
            #                 ),
            #             ], className="input-group"),
            #         ], md=4),
                    
            #         dbc.Col([
            #             html.Label("Search", className="input-label"),
            #             html.Div([
            #                 html.I(className="fas fa-search input-icon"),
            #                 dbc.Input(
            #                     placeholder="Search logs...", 
            #                     className="modern-input"
            #                 ),
            #             ], className="input-group"),
            #         ], md=4),
            #     ], className="filter-row"),
            # ], className="admin-panel filter-panel fade-in-up"),
            
            # Logs Table Panel
            html.Div([
                html.Div([
                    html.I(className="fas fa-list panel-icon"),
                    html.H3("Recent Activity", className="panel-title"),
                ], className="panel-header"),
                
                html.Div([
                    html.Div(
                        id="activity-log-table-container",
                        children=[dcc.Loading(type="circle", color="#2563eb")],
                        className="logs-table-container"
                    ),
                ], className="panel-content"),
            ], className="admin-panel logs-panel fade-in-up"),
            
        ], fluid=True, className="logs-container"),

    ], className="logs-page")


# Additional utility functions for consistent styling
def create_modern_alert(message, alert_type="info"):
    """Create a modern styled alert component."""
    icon_map = {
        "success": "fas fa-check-circle",
        "error": "fas fa-exclamation-circle", 
        "warning": "fas fa-exclamation-triangle",
        "info": "fas fa-info-circle"
    }
    
    return dbc.Alert([
        html.I(className=f"{icon_map.get(alert_type, 'fas fa-info-circle')} me-2"),
        message
    ], color=alert_type, className="modern-alert fade-in")


def create_loading_spinner(text="Loading..."):
    """Create a modern loading component."""
    return html.Div([
        html.Div(className="loading-spinner"),
        html.P(text, className="loading-text"),
    ], className="loading-container")