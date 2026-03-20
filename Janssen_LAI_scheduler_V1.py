# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
import calendar
import datetime
import json
import os
import threading
import time

# 달력 시작 요일 설정 (일요일)
calendar.setfirstweekday(calendar.SUNDAY)

DATA_FILE = "lai_schedule_data_final.json"

DRUG_DATABASE = {
    "인베가 서스티나": ["78mg", "117mg", "156mg", "234mg"],
    "인베가 트린자": ["273mg", "410mg", "546mg", "819mg"],
    "인베가 하피에라": ["1092mg", "1560mg"],
    "아빌리파이 메인테나": ["300mg", "400mg"],
    "아빌리파이 아심투파이": ["720mg", "960mg"],
    "위고비": ["0.25mg", "0.5mg", "1mg", "1.7mg", "2.4mg"],
    "마운자로": ["2.5mg", "5mg", "7.5mg", "10mg", "12.5mg", "15mg"],
    "LAB": [
        "CBC",
        "의료급여WBC",
        "LFT",
        "U/A",
        "Lithium",
        "Valproate",
    ],  # 체크박스를 둘 것
    "메모": ["..."],  # 메모는 세 줄 입력이 가능하도록 한다.
}


class LAI_Scheduler_App:
    def __init__(self, root):
        self.root = root
        self.root.title("LAI 처방 스케줄러 (Dr. Ver. V11 - Silent Save)")
        self.root.geometry("1100x950")

        self.current_date = datetime.date.today()
        self.year = self.current_date.year
        self.month = self.current_date.month

        self.schedule_data = self.load_data()

        self.create_header()
        self.create_calendar_frame()
        self.draw_calendar()

        test_btn = tk.Button(
            self.root,
            text="🔔 알림 강제 테스트 (클릭)",
            command=self.force_check_notification,
            bg="#FF9800",
            fg="white",
            font=("맑은 고딕", 10, "bold"),
        )
        test_btn.pack(pady=10)

        self.root.bind(
            "<F1>", lambda event: self.open_input_dialog(self.current_date.day)
        )

        # 프로그램 시작 3초 후에는 한 번 체크 (출근 시 확인용)
        self.root.after(3000, self.check_and_notify)
        self.start_notification_thread()

    def load_data(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_data(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.schedule_data, f, ensure_ascii=False, indent=4)

    def create_header(self):
        nav_frame = tk.Frame(self.root, pady=10)
        nav_frame.pack(fill=tk.X)

        prev_btn = tk.Button(
            nav_frame, text="◀ 이전 달", command=self.prev_month, font=("맑은 고딕", 10)
        )
        prev_btn.pack(side=tk.LEFT, padx=20)

        self.header_label = tk.Label(
            nav_frame,
            text=f"{self.year}년 {self.month}월",
            font=("맑은 고딕", 20, "bold"),
        )
        self.header_label.pack(side=tk.LEFT, expand=True)

        next_btn = tk.Button(
            nav_frame, text="다음 달 ▶", command=self.next_month, font=("맑은 고딕", 10)
        )
        next_btn.pack(side=tk.LEFT, padx=20)

        days_frame = tk.Frame(self.root)
        days_frame.pack(fill=tk.X, padx=10)
        days = ["일", "월", "화", "수", "목", "금", "토"]
        for i, day in enumerate(days):
            color = "red" if i == 0 else "blue" if i == 6 else "black"
            lbl = tk.Label(
                days_frame,
                text=day,
                font=("맑은 고딕", 11, "bold"),
                fg=color,
                width=14,
                relief="flat",
            )
            lbl.pack(side=tk.LEFT, expand=True, fill=tk.X)

    def create_calendar_frame(self):
        self.calendar_frame = tk.Frame(self.root)
        self.calendar_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)

    def draw_calendar(self):
        for widget in self.calendar_frame.winfo_children():
            widget.destroy()

        self.header_label.config(text=f"{self.year}년 {self.month}월")
        cal = calendar.monthcalendar(self.year, self.month)

        for col in range(7):
            self.calendar_frame.columnconfigure(col, weight=1)

        row = 0
        today = datetime.date.today()

        for week in cal:
            self.calendar_frame.rowconfigure(row, weight=1)
            for col, day in enumerate(week):
                if day != 0:
                    date_key = f"{self.year}-{self.month:02d}-{day:02d}"
                    display_text = f"{day}"
                    bg_color = "white"
                    fg_color = "black"

                    if col == 0:
                        fg_color = "red"
                    elif col == 6:
                        fg_color = "blue"

                    if (
                        self.year == today.year
                        and self.month == today.month
                        and day == today.day
                    ):
                        bg_color = "#FFF59D"
                        display_text += " [오늘]"

                    if date_key in self.schedule_data:
                        items = self.schedule_data[date_key]
                        count = 0
                        for item in items:
                            if count >= 3:
                                display_text += "\n..."
                                break
                            tag = (
                                "(주사)"
                                if item.get("type") == "injection"
                                else "(예정)"
                            )
                            if item.get("type") == "due":
                                bg_color = (
                                    "#E1F5FE"
                                    if bg_color == "white" or bg_color == "#FFF59D"
                                    else bg_color
                                )
                            display_text += f"\n• {item['name']} {tag}"
                            count += 1

                    btn = tk.Button(
                        self.calendar_frame,
                        text=display_text,
                        bg=bg_color,
                        fg=fg_color,
                        justify=tk.LEFT,
                        anchor="nw",
                        font=("맑은 고딕", 9),
                        relief="solid",
                        borderwidth=1,
                    )
                    btn.grid(row=row, column=col, sticky="nsew", padx=0, pady=0)
                    btn.bind(
                        "<Double-Button-1>",
                        lambda event, d=day: self.open_input_dialog(d),
                    )
                else:
                    lbl = tk.Label(self.calendar_frame, bg="#F2F2F2")
                    lbl.grid(row=row, column=col, sticky="nsew")
            row += 1

    def prev_month(self):
        if self.month == 1:
            self.month = 12
            self.year -= 1
        else:
            self.month -= 1
        self.draw_calendar()

    def next_month(self):
        if self.month == 12:
            self.month = 1
            self.year += 1
        else:
            self.month += 1
        self.draw_calendar()

    def open_input_dialog(self, day):
        target_date = datetime.date(self.year, self.month, day)
        date_key = target_date.strftime("%Y-%m-%d")

        dialog = tk.Toplevel(self.root)
        dialog.title(f"기록 관리: {date_key}")
        dialog.geometry("450x700")

        input_frame = tk.LabelFrame(
            dialog,
            text=" [신규 처방 입력] ",
            font=("맑은 고딕", 11, "bold"),
            padx=10,
            pady=10,
        )
        input_frame.pack(fill=tk.X, padx=10, pady=10)

        # 1. 환자명
        tk.Label(input_frame, text="환자명:", font=("맑은 고딕", 9)).grid(
            row=0, column=0, sticky="e", pady=5
        )
        name_entry = tk.Entry(input_frame, width=20)
        name_entry.grid(row=0, column=1, sticky="w", pady=5)
        name_entry.focus_set()

        # 2. 약품명
        tk.Label(input_frame, text="약품명:", font=("맑은 고딕", 9)).grid(
            row=1, column=0, sticky="e", pady=5
        )
        drug_combo = ttk.Combobox(
            input_frame, values=list(DRUG_DATABASE.keys()), state="readonly", width=25
        )
        drug_combo.grid(row=1, column=1, sticky="w", pady=5)

        # 3. 용량
        tk.Label(input_frame, text="용량:", font=("맑은 고딕", 9)).grid(
            row=2, column=0, sticky="e", pady=5
        )
        dosage_combo = ttk.Combobox(input_frame, state="readonly", width=15)
        dosage_combo.grid(row=2, column=1, sticky="w", pady=5)

        def on_drug_select(event):
            selected_drug = drug_combo.get()
            dosages = DRUG_DATABASE.get(selected_drug, [])
            dosage_combo["values"] = dosages
            if dosages:
                dosage_combo.current(0)
            else:
                dosage_combo.set("")

        drug_combo.bind("<<ComboboxSelected>>", on_drug_select)
        drug_combo.current(0)
        on_drug_select(None)

        # 4. 메모
        tk.Label(input_frame, text="메모:", font=("맑은 고딕", 9)).grid(
            row=3, column=0, sticky="ne", pady=5
        )
        memo_text = tk.Text(input_frame, height=2, width=28, font=("맑은 고딕", 9))
        memo_text.grid(row=3, column=1, sticky="w", pady=5)

        # 5. 간격
        tk.Label(input_frame, text="간격(일):", font=("맑은 고딕", 9)).grid(
            row=4, column=0, sticky="e", pady=5
        )
        interval_entry = tk.Entry(input_frame, width=10)
        interval_entry.insert(0, "28")
        interval_entry.grid(row=4, column=1, sticky="w", pady=5)

        def save_action():
            name = name_entry.get().strip()
            drug = drug_combo.get()
            dosage = dosage_combo.get()
            memo = memo_text.get("1.0", tk.END).strip()

            if not name:
                messagebox.showwarning("오류", "환자명을 입력해주세요.")
                return
            try:
                interval = int(interval_entry.get())
            except ValueError:
                messagebox.showerror("오류", "간격은 숫자만 입력해주세요.")
                return

            start_date_str = date_key
            next_date = target_date + datetime.timedelta(days=interval)
            next_date_str = next_date.strftime("%Y-%m-%d")

            record_base = {
                "name": name,
                "drug": drug,
                "dosage": dosage,
                "interval": interval,
                "prescribed_date": start_date_str,
                "next_date": next_date_str,
                "memo": memo,
            }

            if start_date_str not in self.schedule_data:
                self.schedule_data[start_date_str] = []
            rec_inj = record_base.copy()
            rec_inj["type"] = "injection"
            self.schedule_data[start_date_str].append(rec_inj)

            if next_date_str not in self.schedule_data:
                self.schedule_data[next_date_str] = []
            rec_due = record_base.copy()
            rec_due["type"] = "due"
            self.schedule_data[next_date_str].append(rec_due)

            self.save_data()

            # [V11 수정] 저장 시에는 알림 체크(팝업)를 하지 않도록 해당 줄을 제거/주석 처리함
            # self.check_and_notify()  <-- 이 부분이 삭제됨으로써 반복 알림 문제 해결

            messagebox.showinfo(
                "성공", f"저장되었습니다.\n다음 예정일: {next_date_str}"
            )
            dialog.destroy()
            self.draw_calendar()

        save_btn = tk.Button(
            input_frame,
            text="등록하기",
            command=save_action,
            bg="#4CAF50",
            fg="white",
            font=("맑은 고딕", 10, "bold"),
        )
        save_btn.grid(row=5, column=0, columnspan=2, sticky="ew", pady=10)

        list_frame = tk.LabelFrame(
            dialog,
            text=f" [ {date_key} 기록 목록 ] ",
            font=("맑은 고딕", 11, "bold"),
            padx=10,
            pady=10,
        )
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        canvas = tk.Canvas(list_frame)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)
        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        current_items = self.schedule_data.get(date_key, [])
        if not current_items:
            tk.Label(scrollable_frame, text="기록된 내역이 없습니다.", fg="gray").pack(
                pady=20
            )
        else:
            for idx, item in enumerate(current_items):
                item_frame = tk.Frame(
                    scrollable_frame, relief="groove", borderwidth=1, pady=5
                )
                item_frame.pack(fill=tk.X, pady=2, padx=2)

                type_text = "[주사]" if item.get("type") == "injection" else "[예정]"
                type_color = "blue" if item.get("type") == "injection" else "red"

                memo_content = item.get("memo", "")
                memo_display = f"\n메모: {memo_content}" if memo_content else ""

                info_text = f"{type_text} {item['name']}\n{item['drug']} ({item['dosage']}){memo_display}"

                lbl = tk.Label(
                    item_frame,
                    text=info_text,
                    justify=tk.LEFT,
                    fg=type_color,
                    font=("맑은 고딕", 9),
                )
                lbl.pack(side=tk.LEFT, padx=5)

                def delete_item(index=idx):
                    if messagebox.askyesno(
                        "삭제 확인", "정말 이 기록을 삭제하시겠습니까?"
                    ):
                        del self.schedule_data[date_key][index]
                        if not self.schedule_data[date_key]:
                            del self.schedule_data[date_key]
                        self.save_data()
                        dialog.destroy()
                        self.draw_calendar()
                        self.open_input_dialog(day)

                del_btn = tk.Button(
                    item_frame, text="삭제", bg="#FFCDD2", command=delete_item
                )
                del_btn.pack(side=tk.RIGHT, padx=5)

    def start_notification_thread(self):
        t = threading.Thread(target=self.notification_loop, daemon=True)
        t.start()

    def notification_loop(self):
        while True:
            now = datetime.datetime.now()
            # 매일 07:00분 알림
            if now.hour == 7 and now.minute == 0:
                self.check_and_notify()
                time.sleep(61)
            time.sleep(10)

    def force_check_notification(self):
        self.check_and_notify(manual_check=True)

    def check_and_notify(self, manual_check=False):
        today = datetime.date.today()
        alert_lines = []

        # D-Day (오늘)
        today_str = today.strftime("%Y-%m-%d")
        if today_str in self.schedule_data:
            items = [
                f"● [오늘] {item['name']} - {item['drug']} {item['dosage']}"
                for item in self.schedule_data[today_str]
                if item.get("type") == "due"
            ]
            if items:
                alert_lines.extend(items)

        # D+1 (내일)
        tmr = today + datetime.timedelta(days=1)
        tmr_str = tmr.strftime("%Y-%m-%d")
        if tmr_str in self.schedule_data:
            items = [
                f"○ [내일] {item['name']} - {item['drug']} {item['dosage']}"
                for item in self.schedule_data[tmr_str]
                if item.get("type") == "due"
            ]
            if items:
                alert_lines.extend(items)

        # D+2 (모레)
        dat = today + datetime.timedelta(days=2)
        dat_str = dat.strftime("%Y-%m-%d")
        if dat_str in self.schedule_data:
            items = [
                f"○ [모레] {item['name']} - {item['drug']} {item['dosage']}"
                for item in self.schedule_data[dat_str]
                if item.get("type") == "due"
            ]
            if items:
                alert_lines.extend(items)

        if alert_lines:
            title = "📢 LAI 주사 예정 환자 (처방 내역)"
            message = "\n\n".join(alert_lines)
            self.show_custom_notification(title, message)
        else:
            if manual_check:
                messagebox.showinfo(
                    "알림 없음", "오늘, 내일, 모레 예정된 주사 환자가 없습니다."
                )

    def show_custom_notification(self, title, message):
        popup = tk.Toplevel(self.root)
        popup.title("알림")
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#FFF3E0")

        screen_width = popup.winfo_screenwidth()
        screen_height = popup.winfo_screenheight()

        window_width = 450
        window_height = 250
        x_pos = screen_width - window_width - 20
        y_pos = screen_height - window_height - 50

        popup.geometry(f"{window_width}x{window_height}+{x_pos}+{y_pos}")

        tk.Label(
            popup,
            text=title,
            bg="#FF9800",
            fg="white",
            font=("맑은 고딕", 12, "bold"),
            pady=8,
        ).pack(fill=tk.X)

        msg_label = tk.Label(
            popup,
            text=message,
            bg="#FFF3E0",
            font=("맑은 고딕", 10),
            justify=tk.LEFT,
            padx=15,
            pady=10,
            wraplength=420,
        )
        msg_label.pack(expand=True, fill=tk.BOTH)

        def close_popup():
            popup.destroy()

        close_btn = tk.Button(
            popup, text="확인 (창 닫기)", command=close_popup, bg="white", borderwidth=1
        )
        close_btn.pack(pady=10)


if __name__ == "__main__":
    root = tk.Tk()
    app = LAI_Scheduler_App(root)
    root.mainloop()
