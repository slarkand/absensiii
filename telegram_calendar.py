import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def create_calendar(year=None, month=None):
    now = datetime.datetime.now()
    year = year or now.year
    month = month or now.month
    
    keyboard = []
    
    # Header: Month Year
    month_name = datetime.date(year, month, 1).strftime("%B %Y")
    keyboard.append([InlineKeyboardButton(month_name, callback_data="IGNORE")])
    
    # Days of week
    days = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    row = [InlineKeyboardButton(day, callback_data="IGNORE") for day in days]
    keyboard.append(row)
    
    # Determine start day of week and number of days
    # weekday() returns 0 for Monday, 6 for Sunday
    first_day = datetime.date(year, month, 1)
    start_day_of_week = first_day.weekday()
    
    if month == 12:
        next_month_date = datetime.date(year + 1, 1, 1)
    else:
        next_month_date = datetime.date(year, month + 1, 1)
        
    num_days = (next_month_date - first_day).days
    
    # Calendar grid
    date_buttons = []
    for _ in range(start_day_of_week):
        date_buttons.append(InlineKeyboardButton(" ", callback_data="IGNORE"))
        
    for day in range(1, num_days + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        date_buttons.append(InlineKeyboardButton(str(day), callback_data=f"CAL_DATE:{date_str}"))
        
    # Fill the last row with empty buttons
    while len(date_buttons) % 7 != 0:
        date_buttons.append(InlineKeyboardButton(" ", callback_data="IGNORE"))
        
    # Chunk into rows of 7
    for i in range(0, len(date_buttons), 7):
        keyboard.append(date_buttons[i:i+7])
        
    # Navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    keyboard.append([
        InlineKeyboardButton("◀️ Bulan Lalu", callback_data=f"CAL_NAV:{prev_year}:{prev_month}"),
        InlineKeyboardButton("Bulan Depan ▶️", callback_data=f"CAL_NAV:{next_year}:{next_month}")
    ])
    
    return InlineKeyboardMarkup(keyboard)
