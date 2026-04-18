import kivy
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.core.window import Window
from kivy.utils import get_color_from_hex
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import csv
import os
import sqlite3
import shutil
from pathlib import Path

# --- DATA / MODEL ---

POS_FOLDER_NAME = "pos file"
POS_FOLDER_PATH = f"/storage/emulated/0/{POS_FOLDER_NAME}"
DB_PATH = os.path.join(POS_FOLDER_PATH, "pos_data.db")
BACKUP_FOLDER_NAME = "pos backups"
BACKUP_FOLDER_PATH = f"/storage/emulated/0/{BACKUP_FOLDER_NAME}"

def ensure_pos_folder():
    """Ensure POS folder exists."""
    if not os.path.exists(POS_FOLDER_PATH):
        try:
            os.makedirs(POS_FOLDER_PATH)
        except Exception as e:
            show_popup("Storage Error", f"Failed to create folder: {POS_FOLDER_PATH}\n{e}")


def ensure_backup_folder():
    """Ensure backup folder exists."""
    if not os.path.exists(BACKUP_FOLDER_PATH):
        try:
            os.makedirs(BACKUP_FOLDER_PATH)
        except Exception as e:
            show_popup("Backup Error", f"Failed to create backup folder: {BACKUP_FOLDER_PATH}\n{e}")


def show_popup(title, message):
    """Display a popup message."""
    popup = Popup(
        title=title,
        content=Label(text=message, color=[1,1,1,1]),
        size_hint=(0.8, 0.3),
        background='atlas://data/images/defaulttheme/button_pressed',
        auto_dismiss=True,
    )
    popup.open()

def get_db():
    """Get database connection."""
    ensure_pos_folder()
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    """Initialize database with schema."""
    conn = get_db()
    c = conn.cursor()
    
    # Create customers table with balance column
    c.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            balance TEXT DEFAULT '0.00'
        )
    ''')
    
c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            type TEXT,
            amount TEXT,
            note TEXT,
            dt TEXT,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    
    # Migrate existing data if needed
    migrate_to_decimal()

def migrate_to_decimal():
    """Migrate old float data to Decimal and add balance column if missing."""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Check if balance column exists
        c.execute("PRAGMA table_info(customers)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'balance' not in columns:
            c.execute("ALTER TABLE customers ADD COLUMN balance TEXT DEFAULT '0.00'")
            conn.commit()
        
        # Recalculate all balances
        c.execute("SELECT id FROM customers")
        customer_ids = [row[0] for row in c.fetchall()]
        
        for cid in customer_ids:
            balance = Decimal('0.00')
            c.execute("SELECT type, amount FROM transactions WHERE customer_id=? ORDER BY dt, id", (cid,))
            for ttype, amt_str in c.fetchall():
                try:
                    amt = Decimal(str(amt_str)) if isinstance(amt_str, str) else Decimal(str(amt_str))
                    if ttype == "Deposit":
                        balance += amt
                    else:
                        balance -= amt
                except:
                    pass
            
            c.execute("UPDATE customers SET balance=? WHERE id=?", (str(balance), cid))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration error: {e}")

def format_currency(value):
    """Format Decimal value as currency string."""
    if isinstance(value, str):
        value = Decimal(value)
    elif isinstance(value, float):
        value = Decimal(str(value))
    elif not isinstance(value, Decimal):
        value = Decimal(str(value))
    
    return "{:,.2f}".format(value)

def get_download_path():
    """Get download directory path."""
    return "/storage/emulated/0/Download/"

# ---- Database Operations ----

def get_customers():
    """Get list of all customer names."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM customers ORDER BY name COLLATE NOCASE")
    names = [row[0] for row in c.fetchall()]
    conn.close()
    return names

def add_customer_db(name):
    """Add new customer to database."""
    conn = get_db()
    try:
        conn.execute("INSERT INTO customers (name, balance) VALUES (?, ?)", (name, '0.00'))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_customer_db(name):
    """Delete customer and all their transactions."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM customers WHERE name=?", (name,))
    row = c.fetchone()
    if row:
        customer_id = row[0]
        c.execute("DELETE FROM transactions WHERE customer_id=?", (customer_id,))
        c.execute("DELETE FROM customers WHERE id=?", (customer_id,))
        conn.commit()
    conn.close()

def add_transaction_db(customer_name, ttype, amount, note, dt):
    """Add transaction and update customer balance."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT id, balance FROM customers WHERE name=?", (customer_name,))
        row = c.fetchone()
        if not row:
            conn.close()
            return False
        
        customer_id = row[0]
        current_balance = Decimal(row[1]) if row[1] else Decimal('0.00')
        
        # Convert amount to Decimal
        amount_decimal = Decimal(str(amount))
        
        # Calculate new balance
        if ttype == "Deposit":
            new_balance = current_balance + amount_decimal
        else:
            new_balance = current_balance - amount_decimal
        
        # Insert transaction
        c.execute(
            "INSERT INTO transactions (customer_id, type, amount, note, dt) VALUES (?, ?, ?, ?, ?)",
            (customer_id, ttype, str(amount_decimal), note, dt.strftime("%Y-%m-%d %H:%M:%S"))
        )
        
        # Update customer balance
        c.execute("UPDATE customers SET balance=? WHERE id=?", (str(new_balance), customer_id))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Transaction error: {e}")
        return False
    finally:
        conn.close()

def edit_transaction_db(trans_id, amount, note):
    """Edit transaction amount and note, recalculate affected balances."""
    conn = get_db()
    try:
        c = conn.cursor()
        
        # Get the transaction and customer info
        c.execute("""
            SELECT t.customer_id, t.type, t.amount, c.balance 
            FROM transactions t
            JOIN customers c ON t.customer_id = c.id
            WHERE t.id = ?
        """, (trans_id,))
        
        row = c.fetchone()
        if not row:
            conn.close()
            return
        
        customer_id, ttype, old_amt_str, current_balance = row
        
        old_amt = Decimal(old_amt_str)
        new_amt = Decimal(str(amount))
        current_bal = Decimal(current_balance)
        
        # Reverse old transaction effect
        if ttype == "Deposit":
            adjusted_balance = current_bal - old_amt
        else:
            adjusted_balance = current_bal + old_amt
        
        # Apply new transaction effect
        if ttype == "Deposit":
            final_balance = adjusted_balance + new_amt
        else:
            final_balance = adjusted_balance - new_amt
        
        # Update transaction and balance
        c.execute("UPDATE transactions SET amount=?, note=? WHERE id=?", (str(new_amt), note, trans_id))
        c.execute("UPDATE customers SET balance=? WHERE id=?", (str(final_balance), customer_id))
        
        conn.commit()
    except Exception as e:
        print(f"Edit transaction error: {e}")
    finally:
        conn.close()

def delete_transaction_db(trans_id):
    """Delete transaction and recalculate customer balance."""
    conn = get_db()
    try:
        c = conn.cursor()
        
        # Get transaction details
        c.execute("""
            SELECT t.customer_id, t.type, t.amount, c.balance 
            FROM transactions t
            JOIN customers c ON t.customer_id = c.id
            WHERE t.id = ?
        """, (trans_id,))
        
        row = c.fetchone()
        if not row:
            conn.close()
            return
        
        customer_id, ttype, amt_str, current_balance = row
        
        amt = Decimal(amt_str)
        current_bal = Decimal(current_balance)
        
        # Reverse transaction effect
        if ttype == "Deposit":
            new_balance = current_bal - amt
        else:
            new_balance = current_bal + amt
        
        # Delete and update
        c.execute("DELETE FROM transactions WHERE id=?", (trans_id,))
        c.execute("UPDATE customers SET balance=? WHERE id=?", (str(new_balance), customer_id))
        
        conn.commit()
    except Exception as e:
        print(f"Delete transaction error: {e}")
    finally:
        conn.close()

def get_transactions_db(customer_name):
    """Get all transactions for a customer."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM customers WHERE name=?", (customer_name,))
    row = c.fetchone()
    if not row:
        conn.close()
        return []
    customer_id = row[0]
    c.execute("SELECT id, type, amount, note, dt FROM transactions WHERE customer_id=? ORDER BY dt, id", (customer_id,))
    txs = []
    for (tid, ttype, amount, note, dt_str) in c.fetchall():
        txs.append({
            "id": tid,
            "type": ttype,
            "amount": Decimal(str(amount)),
            "note": note,
            "dt": datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        })
    conn.close()
    return txs

def get_balance(customer_name):
    """Get customer balance (now retrieved from database, not recalculated)."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance FROM customers WHERE name=?", (customer_name,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        return Decimal(row[0])
    return Decimal('0.00')

def get_total_balance():
    """Get total balance across all customers."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT SUM(CAST(balance AS REAL)) FROM customers")
    row = c.fetchone()
    conn.close()
    total = row[0] if row[0] else 0
    return Decimal(str(total))

def get_sorted_customers_by_balance():
    """Get customers sorted by balance descending."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, balance FROM customers ORDER BY CAST(balance AS REAL) DESC")
    results = [(name, Decimal(bal)) for name, bal in c.fetchall()]
    conn.close()
    return results

def backup_database():
    """Create a backup of the database file with timestamp."""
    ensure_backup_folder()
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"pos_data_backup_{timestamp}.db"
        backup_path = os.path.join(BACKUP_FOLDER_PATH, backup_filename)
        
        shutil.copy2(DB_PATH, backup_path)
        return backup_path
    except Exception as e:
        print(f"Backup error: {e}")
        return None

def export_to_csv(customer_name):
    """Export customer transactions to CSV."""
    txs = get_transactions_db(customer_name)
    filename = f"{customer_name}_transactions.csv"
    path = os.path.join(get_download_path(), filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Time", "Type", "Amount", "Note", "Running Balance"])
        running = Decimal('0.00')
        for t in txs:
            dt = t["dt"]
            amt = t["amount"] if t["type"] == "Deposit" else -t["amount"]
            running += amt
            writer.writerow([
                dt.strftime("%Y-%m-%d"),
                dt.strftime("%H:%M:%S"),
                t["type"],
                format_currency(t["amount"]),
                t["note"],
                format_currency(running)
            ])
    return path

def export_all_balances_csv():
    """Export all customer balances to CSV."""
    filename = "all_customers_balances.csv"
    path = os.path.join(get_download_path(), filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Customer Name", "Balance"])
        for name, bal in get_sorted_customers_by_balance():
            writer.writerow([name, format_currency(bal)])
    return path

def export_to_excel(customer_name):
    """Export customer transactions to Excel."""
    try:
        import xlsxwriter
    except ImportError:
        show_popup("Export Error", "xlsxwriter not available. Export as CSV instead.")
        return None
    txs = get_transactions_db(customer_name)
    filename = f"{customer_name}_transactions.xlsx"
    path = os.path.join(get_download_path(), filename)
    workbook = xlsxwriter.Workbook(path)
    worksheet = workbook.add_worksheet()
    headers = ["Date", "Time", "Type", "Amount", "Note", "Running Balance"]
    for col, h in enumerate(headers):
        worksheet.write(0, col, h)
    running = Decimal('0.00')
    for row, t in enumerate(txs, 1):
        dt = t["dt"]
        amt = t["amount"] if t["type"] == "Deposit" else -t["amount"]
        running += amt
        worksheet.write(row, 0, dt.strftime("%Y-%m-%d"))
        worksheet.write(row, 1, dt.strftime("%H:%M:%S"))
        worksheet.write(row, 2, t["type"])
        worksheet.write(row, 3, float(t["amount"]))
        worksheet.write(row, 4, t["note"])
        worksheet.write(row, 5, float(running))
    workbook.close()
    return path

def export_all_balances_excel():
    """Export all customer balances to Excel."""
    try:
        import xlsxwriter
    except ImportError:
        show_popup("Export Error", "xlsxwriter not available. Export as CSV instead.")
        return None
    filename = "all_customers_balances.xlsx"
    path = os.path.join(get_download_path(), filename)
    workbook = xlsxwriter.Workbook(path)
    worksheet = workbook.add_worksheet()
    worksheet.write(0, 0, "Customer Name")
    worksheet.write(0, 1, "Balance")
    row = 1
    for name, bal in get_sorted_customers_by_balance():
        worksheet.write(row, 0, name)
        worksheet.write(row, 1, float(bal))
        row += 1
    workbook.close()
    return path

# --- VIEW / PRESENTER ---

Window.clearcolor = (0.09, 0.1, 0.12, 1)
Window.size = (720, 1480)

class MainMenu(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', padding=30, spacing=18)
        self.total_label = Label(
            text='',
            markup=True,
            font_size=32,
            color=[1,1,1,1],
            size_hint=(1, 0.08),
            bold=True
        )
        self.layout.add_widget(self.total_label)
        self.layout.add_widget(Label(
            text='[b][color=DDDDDD][size=37]Point of Sale[/size][/color][/b]',
            markup=True,
            size_hint=(1, 0.09),
            color=[1,1,1,1])
        )
        add_box = BoxLayout(orientation='horizontal', spacing=10, size_hint=(1, 0.06))
        self.add_name_input = TextInput(
            hint_text="New customer name",
            multiline=False,
            size_hint=(0.7, 1),
            background_color=[0.22,0.23,0.27,1], foreground_color=[1,1,1,1],
            cursor_color=[1,1,1,1]
        )
        add_btn = Button(
            text="Add",
            background_color=get_color_from_hex("#43A047"),
            size_hint=(0.3, 1),
            color=[1,1,1,1]
        )
        add_btn.bind(on_release=self.add_customer)
        add_box.add_widget(self.add_name_input)
        add_box.add_widget(add_btn)
        self.layout.add_widget(add_box)
        sel_box = BoxLayout(orientation='horizontal', spacing=10, size_hint=(1, 0.06))
        self.spinner = Spinner(
            text="Select Customer",
            values=get_customers(),
            size_hint=(0.7, 1),
            background_color=get_color_from_hex("#23232c"),
            color=[1,1,1,1]
        )
        self.spinner.bind(text=self.on_customer_selected)
        del_btn = Button(
            text="Delete",
            background_color=get_color_from_hex("#E53935"),
            size_hint=(0.3, 1),
            color=[1,1,1,1]
        )
        del_btn.bind(on_release=self.delete_customer)
        sel_box.add_widget(self.spinner)
        sel_box.add_widget(del_btn)
        self.layout.add_widget(sel_box)
        self.bal_label = Label(text="", size_hint=(1, 0.045), color=[1,1,1,1])
        self.layout.add_widget(self.bal_label)
        trans_box = BoxLayout(orientation='horizontal', spacing=10, size_hint=(1, 0.06))
        self.amount_input = TextInput(
            hint_text="Amount",
            input_filter='float',
            multiline=False,
            size_hint=(0.25, 1),
            background_color=[0.22,0.23,0.27,1], foreground_color=[1,1,1,1],
            cursor_color=[1,1,1,1]
        )
        self.note_input = TextInput(
            hint_text="Optional Note",
            multiline=False,
            size_hint=(0.45, 1),
            background_color=[0.22,0.23,0.27,1], foreground_color=[1,1,1,1],
            cursor_color=[1,1,1,1]
        )
        dep_btn = Button(
            text="C IN",
            background_color=get_color_from_hex("#43A047"),
            size_hint=(0.15, 1),
            color=[1,1,1,1]
        )
        dep_btn.bind(on_release=lambda inst: self.add_transaction('Deposit'))
        with_btn = Button(
            text="C OUT",
            background_color=get_color_from_hex("#FF9800"),
            size_hint=(0.15, 1),
            color=[1,1,1,1]
        )
        with_btn.bind(on_release=lambda inst: self.add_transaction('Withdraw'))
        trans_box.add_widget(self.amount_input)
        trans_box.add_widget(self.note_input)
        trans_box.add_widget(dep_btn)
        trans_box.add_widget(with_btn)
        self.layout.add_widget(trans_box)
        nav_box = BoxLayout(orientation='horizontal', spacing=10, size_hint=(1, 0.06))
        view_btn = Button(
            text="Customer Details",
            background_color=get_color_from_hex("#3949AB"),
            size_hint=(0.5, 1),
            color=[1,1,1,1]
        )
        view_btn.bind(on_release=self.goto_customer)
        exp_btn = Button(
            text="Export CSV",
            background_color=get_color_from_hex("#00897B"),
            size_hint=(0.25, 1),
            color=[1,1,1,1]
        )
        exp_btn.bind(on_release=self.export_csv)
        expx_btn = Button(
            text="Export Excel",
            background_color=get_color_from_hex("#7B1FA2"),
            size_hint=(0.25, 1),
            color=[1,1,1,1]
        )
        expx_btn.bind(on_release=self.export_excel)
        nav_box.add_widget(view_btn)
        nav_box.add_widget(exp_btn)
        nav_box.add_widget(expx_btn)
        self.layout.add_widget(nav_box)
        all_balances_label = Label(
            text="[b][color=FFFFFF]All Customers' Balances[/color][/b]",
            markup=True,
            size_hint=(1, 0.04),
            color=[1,1,1,1]
        )
        self.layout.add_widget(all_balances_label)
        self.balances_scroll = ScrollView(size_hint=(1, 0.22))
        self.balances_grid = GridLayout(cols=1, size_hint_y=None, spacing=6, padding=6)
        self.balances_grid.bind(minimum_height=self.balances_grid.setter('height'))
        self.balances_scroll.add_widget(self.balances_grid)
        self.layout.add_widget(self.balances_scroll)
        all_export_box = BoxLayout(orientation="horizontal", spacing=10, size_hint=(1, 0.07))
        all_csv_btn = Button(
            text="Export All Balances CSV",
            background_color=get_color_from_hex("#4CAF50"),
            size_hint=(0.5, 1),
            color=[1,1,1,1]
        )
        all_csv_btn.bind(on_release=self.export_all_balances_csv)
        all_xls_btn = Button(
            text="Export All Balances Excel",
            background_color=get_color_from_hex("#8E24AA"),
            size_hint=(0.5, 1),
            color=[1,1,1,1]
        )
        all_xls_btn.bind(on_release=self.export_all_balances_excel)
        all_export_box.add_widget(all_csv_btn)
        all_export_box.add_widget(all_xls_btn)
        self.layout.add_widget(all_export_box)
        
        # PANIC BUTTON - Database Backup
        backup_btn = Button(
            text="🛡️ Backup Database",
            background_color=get_color_from_hex("#D32F2F"),
            size_hint=(1, 0.06),
            color=[1,1,1,1],
            bold=True
        )
        backup_btn.bind(on_release=self.backup_database_action)
        self.layout.add_widget(backup_btn)
        
        self.layout.add_widget(Label(
            text="[i][color=BBBBBB]Tap above to manage customers and transactions[/color][/i]",
            markup=True,
            size_hint=(1, 0.032),
            color=[1,1,1,1]
        ))
        self.add_widget(self.layout)

    def refresh(self):
        self.spinner.values = get_customers()
        self.spinner.text = "Select Customer"
        self.bal_label.text = ""
        self.update_all_balances()
        self.update_total_label()

    def update_total_label(self):
        total = get_total_balance()
        self.total_label.text = f"[b][color=FFFFFF]Total Money: {format_currency(total)}[/color][/b]"
        self.total_label.markup = True

    def add_customer(self, instance):
        name = self.add_name_input.text.strip()
        if not name:
            show_popup("Error", "Customer name required.")
        elif name in get_customers():
            show_popup("Error", "Customer exists.")
        else:
            add_customer_db(name)
            self.spinner.values = get_customers()
            self.spinner.text = "Select Customer"
            show_popup("Success", f"Customer '{name}' added.")
        self.add_name_input.text = ""
        self.update_all_balances()
        self.update_total_label()

    def delete_customer(self, instance):
        name = self.spinner.text
        if name in get_customers():
            content = BoxLayout(orientation='vertical', spacing=16, padding=10)
            lbl = Label(
                text=f"Delete '{name}' and all records?",
                color=[1,1,1,1],
                size_hint_y=0.6
            )
            btn_box = BoxLayout(orientation='horizontal', spacing=20, size_hint_y=0.4)
            btn_yes = Button(
                text="Yes, Delete",
                background_color=get_color_from_hex("#E53935"),
                color=[1,1,1,1]
            )
            btn_no = Button(
                text="Cancel",
                background_color=get_color_from_hex("#888888"),
                color=[1,1,1,1]
            )
            popup = Popup(
                title="Confirm Delete",
                content=content,
                size_hint=(0.7,0.3),
                auto_dismiss=False,
                background='atlas://data/images/defaulttheme/button_pressed'
            )
            btn_yes.bind(on_release=lambda x: self._do_delete_customer(popup, name))
            btn_no.bind(on_release=popup.dismiss)
            btn_box.add_widget(btn_yes)
            btn_box.add_widget(btn_no)
            content.add_widget(lbl)
            content.add_widget(btn_box)
            popup.open()
        else:
            show_popup("Error", "Select a customer to delete.")

    def _do_delete_customer(self, popup, name):
        delete_customer_db(name)
        self.spinner.values = get_customers()
        self.spinner.text = "Select Customer"
        self.bal_label.text = ""
        popup.dismiss()
        show_popup("Deleted", f"Customer '{name}' deleted.")
        self.update_all_balances()
        self.update_total_label()

    def add_transaction(self, ttype):
        name = self.spinner.text
        amt = self.amount_input.text.strip()
        note = self.note_input.text.strip()
        if name not in get_customers():
            show_popup("Error", "Select a customer.")
            return
        try:
            amount = Decimal(amt)
            if amount <= 0:
                raise ValueError
        except:
            show_popup("Error", "Enter a valid amount.")
            return
        if add_transaction_db(name, ttype, amount, note, datetime.now()):
            self.spinner.text = "Select Customer"
            self.bal_label.text = ""
            self.amount_input.text = ""
            self.note_input.text = ""
            show_popup("Success", f"{ttype} of {format_currency(amount)} added.")
            self.update_all_balances()
            self.update_total_label()
        else:
            show_popup("Error", "Failed to add transaction.")

    def goto_customer(self, instance):
        name = self.spinner.text
        if name in get_customers():
            self.manager.get_screen('customer').set_customer(name)
            self.manager.current = 'customer'
        else:
            show_popup("Error", "Select a customer.")

    def export_csv(self, instance):
        name = self.spinner.text
        if name in get_customers():
            path = export_to_csv(name)
            show_popup("Exported", f"Saved to {path}")
        else:
            show_popup("Error", "Select a customer.")

    def export_excel(self, instance):
        name = self.spinner.text
        if name in get_customers():
            try:
                path = export_to_excel(name)
                if path:
                    show_popup("Exported", f"Saved to {path}")
            except Exception as e:
                show_popup("Export Error", f"{e}\nTry exporting CSV.")
        else:
            show_popup("Error", "Select a customer.")

    def export_all_balances_csv(self, instance):
        path = export_all_balances_csv()
        show_popup("Exported", f"All balances saved to {path}")

    def export_all_balances_excel(self, instance):
        try:
            path = export_all_balances_excel()
            if path:
                show_popup("Exported", f"All balances saved to {path}")
        except Exception as e:
            show_popup("Export Error", f"{e}\nTry exporting CSV.")

    def backup_database_action(self, instance):
        """Panic button: Backup entire database."""
        backup_path = backup_database()
        if backup_path:
            show_popup("Backup Success", f"Database backed up to:\n{backup_path}")
        else:
            show_popup("Backup Failed", "Could not create database backup.")

    def update_all_balances(self):
        self.balances_grid.clear_widgets()
        sorted_custs = get_sorted_customers_by_balance()
        if not sorted_custs:
            self.balances_grid.add_widget(Label(
                text="No customers yet.",
                size_hint_y=None,
                height=40,
                color=[0.8,0.8,0.8,1]
            ))
        else:
            for name, bal in sorted_custs:
                color = "43A047" if bal >= 0 else "E53935"
                balance_box = BoxLayout(orientation='horizontal', size_hint_y=None, height=40, padding=(0,0,0,0))
                name_label = Label(
                    text=f"[b]{name}[/b]",
                    markup=True,
                    font_size=20,
                    size_hint_x=0.55,
                    halign="left",
                    valign="middle",
                    color=[1,1,1,1],
                )
                name_label.bind(size=lambda inst, val: setattr(inst, 'text_size', inst.size))
                bal_label = Label(
                    text=f"[color={color}]{format_currency(bal)}[/color]",
                    markup=True,
                    font_size=20,
                    size_hint_x=0.45,
                    halign="left",
                    valign="middle",
                    color=[1,1,1,1],
                )
                bal_label.bind(size=lambda inst, val: setattr(inst, 'text_size', inst.size))
                balance_box.add_widget(name_label)
                balance_box.add_widget(bal_label)
                self.balances_grid.add_widget(balance_box)

    def on_customer_selected(self, spinner, value):
        if value in get_customers():
            bal = get_balance(value)
            self.bal_label.text = f"[b][color=FFFFFF]Balance: {format_currency(bal)}[/color][/b]"
            self.bal_label.markup = True
        else:
            self.bal_label.text = ""

class CustomerScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name_label = Label(
            text="", font_size=28, size_hint=(1, 0.08),
            color=[1,1,1,1]
        )
        self.bal_label = Label(
            text="", font_size=22, size_hint=(1, 0.06),
            color=[1,1,1,1]
        )
        self.trans_scroll = ScrollView(size_hint=(1, 0.7))
        self.trans_grid = GridLayout(cols=1, size_hint_y=None, spacing=10, padding=10)
        self.trans_grid.bind(minimum_height=self.trans_grid.setter('height'))
        self.trans_scroll.add_widget(self.trans_grid)
        back_btn = Button(
            text="Back",
            size_hint=(1, 0.08),
            background_color=get_color_from_hex("#039BE5"),
            color=[1,1,1,1]
        )
        back_btn.bind(on_release=self.go_back)

        self.layout = BoxLayout(orientation='vertical', padding=20, spacing=10)
        self.layout.add_widget(self.name_label)
        self.layout.add_widget(self.bal_label)
        self.layout.add_widget(self.trans_scroll)
        self.layout.add_widget(back_btn)
        self.add_widget(self.layout)
        self.current_customer = None

    def set_customer(self, name):
        self.current_customer = name
        self.name_label.text = f"[b][color=FFFFFF]{name}[/color][/b]"
        self.bal_label.text = f"[b][color=FFFFFF]Balance: {format_currency(get_balance(name))}[/color][/b]"
        self.name_label.markup = True
        self.bal_label.markup = True
        self.update_transactions()

    def update_transactions(self):
        self.trans_grid.clear_widgets()
        records = get_transactions_db(self.current_customer)
        if not records:
            self.trans_grid.add_widget(Label(
                text="No transactions.",
                size_hint_y=None,
                height=60,
                color=[0.8,0.8,0.8,1]
            ))
            return
        running = Decimal('0.00')
        for idx, t in enumerate(records):
            tbox = BoxLayout(orientation='horizontal', size_hint_y=None, height=120, spacing=12, padding=(0,6,0,6))
            left = BoxLayout(orientation='vertical', size_hint=(0.55, 1))
            dt = t['dt']
            left.add_widget(Label(
                text=f"{dt.strftime('%Y-%m-%d %H:%M:%S')}",
                font_size=14,
                color=[0.7,0.7,0.7,1]
            ))
            left.add_widget(Label(
                text=f"{t['type']}: [b]{format_currency(t['amount'])}[/b]",
                font_size=23, markup=True,
                color=[1,1,1,1]
            ))
            left.add_widget(Label(
                text=f"[i]{t['note']}[/i]",
                font_size=16, markup=True,
                color=[0.7,0.7,0.7,1]
            ))
            amt = t['amount'] if t['type'] == 'Deposit' else -t['amount']
            running += amt
            running_label = Label(
                text=f"Running: [b]{format_currency(running)}[/b]",
                font_size=18, markup=True,
                color=[0.2,0.6,1,1]
            )
            left.add_widget(running_label)

            # Extra large, side-by-side Edit/Delete buttons
            button_box = BoxLayout(orientation='horizontal', size_hint=(0.45, 1), spacing=12)
            edit_btn = Button(
                text="Edit",
                size_hint=(0.5, 1),
                font_size=28,
                background_color=get_color_from_hex("#FFB300"),
                color=[1,1,1,1],
                height=100
            )
            edit_btn.bind(on_release=lambda inst, trans_id=t["id"]: self.edit_trans(trans_id))
            del_btn = Button(
                text="Delete",
                size_hint=(0.5, 1),
                font_size=28,
                background_color=get_color_from_hex("#E53935"),
                color=[1,1,1,1],
                height=100
            )
            del_btn.bind(on_release=lambda inst, trans_id=t["id"]: self.delete_trans(trans_id))
            button_box.add_widget(edit_btn)
            button_box.add_widget(del_btn)

            tbox.add_widget(left)
            tbox.add_widget(button_box)
            self.trans_grid.add_widget(tbox)

    def edit_trans(self, trans_id):
        # Find transaction by id
        records = get_transactions_db(self.current_customer)
        t = next((x for x in records if x["id"] == trans_id), None)
        if not t:
            show_popup("Error", "Transaction not found.")
            return
        content = BoxLayout(orientation='vertical', spacing=8)
        amt_in = TextInput(
            text=str(t['amount']),
            multiline=False,
            input_filter='float',
            size_hint=(1, 0.4),
            background_color=[0.22,0.23,0.27,1],
            foreground_color=[1,1,1,1],
            cursor_color=[1,1,1,1]
        )
        note_in = TextInput(
            text=t['note'],
            multiline=False,
            size_hint=(1, 0.4),
            background_color=[0.22,0.23,0.27,1],
            foreground_color=[1,1,1,1],
            cursor_color=[1,1,1,1]
        )
        save_btn = Button(
            text="Save",
            background_color=get_color_from_hex("#43A047"),
            size_hint=(1, 0.5),
            color=[1,1,1,1]
        )
        content.add_widget(Label(text="Edit Amount:", color=[1,1,1,1]))
        content.add_widget(amt_in)
        content.add_widget(Label(text="Edit Note:", color=[1,1,1,1]))
        content.add_widget(note_in)
        content.add_widget(save_btn)
        popup = Popup(title="Edit Transaction", content=content, size_hint=(0.8, 0.5), auto_dismiss=True)
        def save_edit(inst):
            try:
                new_amt = Decimal(amt_in.text)
                if new_amt <= 0:
                    raise ValueError
                edit_transaction_db(trans_id, new_amt, note_in.text)
                popup.dismiss()
                self.bal_label.text = f"[b][color=FFFFFF]Balance: {format_currency(get_balance(self.current_customer))}[/color][/b]"
                self.bal_label.markup = True
                self.update_transactions()
                self.manager.get_screen('main').update_all_balances()
                self.manager.get_screen('main').update_total_label()
                show_popup("Saved", "Transaction updated.")
            except:
                show_popup("Error", "Invalid amount.")
        save_btn.bind(on_release=save_edit)
        popup.open()

    def delete_trans(self, trans_id):
        def do_del(inst):
            delete_transaction_db(trans_id)
            self.bal_label.text = f"[b][color=FFFFFF]Balance: {format_currency(get_balance(self.current_customer))}[/color][/b]"
            self.bal_label.markup = True
            self.update_transactions()
            self.manager.get_screen('main').update_all_balances()
            self.manager.get_screen('main').update_total_label()
            popup.dismiss()
            show_popup("Deleted", "Transaction deleted.")
        popup = Popup(title="Delete?", content=Button(text="Yes, Delete", on_release=do_del, color=[1,1,1,1]), size_hint=(0.7, 0.3))
        popup.open()

    def go_back(self, instance):
        self.manager.get_screen('main').refresh()
        self.manager.current = 'main'

class POSApp(App):
    def build(self):
        ensure_pos_folder()
        init_db()
        sm = ScreenManager(transition=NoTransition())
        sm.add_widget(MainMenu(name='main'))
        sm.add_widget(CustomerScreen(name='customer'))
        return sm

    def on_start(self):
        self.root.get_screen('main').refresh()

if __name__ == '__main__':
    POSApp().run()