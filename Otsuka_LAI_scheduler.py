# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
import calendar
import datetime
import json
import os
import threading
import time
from tkinter import filedialog

from PIL import Image, ImageTk, ImageDraw, ImageFilter
from icalendar import Calendar, Event
import pytz

# Google Calendar API Imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 달력 시작 요일 설정 (일요일)
calendar.setfirstweekday(calendar.SUNDAY)

DATA_FILE = "otsuka_schedule_data_final.json"
CONFIG_FILE = "otsuka_config.json"

DRUG_DATABASE = {
    "아빌리파이 메인테나": ["300mg", "400mg"],
    "아빌리파이 아심투파이": ["720mg", "960mg"],
    "인베가 서스티나": ["78mg", "117mg", "156mg", "234mg"],
    "인베가 트린자": ["273mg", "410mg", "546mg", "819mg"],
    "인베가 하피에라": ["1092mg", "1560mg"],
    "위고비": ["0.25mg", "0.5mg", "1mg", "1.7mg", "2.4mg"],
    "마운자로": ["2.5mg", "5mg", "7.5mg", "10mg", "12.5mg", "15mg"],
    "메모": ["..."],  # 메모는 세 줄 입력이 가능하도록 한다.
}


class LAI_Scheduler_App:
    def __init__(self, root):
        self.root = root
        self.root.title("Otsuka LAI Scheduler(Dr.Ver.V01)")
        self.root.geometry("1200x800") 
        
        try:
            icon_img = tk.PhotoImage(file="data_image/Otsuka_ico.png")
            self.root.iconphoto(False, icon_img)
        except Exception:
            pass

        self.current_date = datetime.date.today()
        self.year = self.current_date.year
        self.month = self.current_date.month

        self.schedule_data = self.load_data()
        self.config = self.load_config()

        # Main frame
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(2, weight=1)
        main_frame.rowconfigure(3, weight=0) # Footer row
        main_frame.columnconfigure(0, weight=1)

        self.create_header(main_frame)
        self.create_calendar_frame(main_frame)
        self.create_footer(main_frame)
        self.draw_calendar()

        self.root.bind(
            "<F1>", lambda event: self.open_input_dialog(self.current_date.day, None)
        )

        self.drag_item = None
        self.drag_widget = None
        self.drop_target_frame = None
        self.day_frames = []
        self.last_notification_check_date = None
        self.notification_lock = threading.Lock()
        # 열린 알림 팝업 추적 (level 순서: dat → tomorrow → today 순으로 닫기)
        self.open_popups = {"today": None, "tomorrow": None, "dat": None}

        self.root.bind("<Alt-k>", self._close_one_popup)
        self.root.bind("<Alt-K>", self._close_all_popups)

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
        self.sync_ics_file()
        if os.path.exists('token.json'):
            self.sync_google_calendar_silent()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"sync_path": None}

    def save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def set_sync_path(self):
        path = filedialog.askdirectory(title="클라우드 동기화 폴더를 선택하세요")
        if path:
            self.config["sync_path"] = path
            self.save_config()
            messagebox.showinfo("성공", f"동기화 폴더가 '{path}'로 설정되었습니다.")
            self.sync_ics_file() # Immediately sync after setting the path

    def generate_event_id(self, item, date_key):
        raw_id = f"{item.get('record_id', '')}{item.get('type', '')}{date_key}"
        encoded = raw_id.encode('utf-8').hex()
        return encoded

    SCOPES = ['https://www.googleapis.com/auth/calendar']

    def authenticate_google_calendar(self):
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', self.SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None
            if not creds:
                if not os.path.exists('credentials.json'):
                    return None, "credentials.json 파일이 없습니다.\n구글 클라우드 콘솔에서 발급받은 파일을 프로그램 폴더에 넣어주세요."
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
                
        service = build('calendar', 'v3', credentials=creds)
        return service, ""

    def get_or_create_calendar(self, service, summary="Otsuka LAI Scheduler"):
        page_token = None
        while True:
            calendar_list = service.calendarList().list(pageToken=page_token).execute()
            for calendar_list_entry in calendar_list['items']:
                if calendar_list_entry['summary'] == summary:
                    return calendar_list_entry['id']
            page_token = calendar_list.get('nextPageToken')
            if not page_token:
                break
                
        calendar = {'summary': summary, 'timeZone': 'Asia/Seoul'}
        created_calendar = service.calendars().insert(body=calendar).execute()
        return created_calendar['id']

    def sync_google_calendar(self):
        threading.Thread(target=self._sync_google_calendar_thread, args=(False,), daemon=True).start()
        
    def sync_google_calendar_silent(self):
        threading.Thread(target=self._sync_google_calendar_thread, args=(True,), daemon=True).start()

    def _sync_google_calendar_thread(self, silent=False):
        try:
            service, err_msg = self.authenticate_google_calendar()
            if not service:
                if not silent:
                    self.root.after(0, lambda: messagebox.showerror("인증 오류", err_msg))
                return
                
            cal_id = self.get_or_create_calendar(service)
            
            existing_events = {}
            page_token = None
            while True:
                events_result = service.events().list(calendarId=cal_id, pageToken=page_token).execute()
                for e in events_result.get('items', []):
                    existing_events[e['id']] = e
                page_token = events_result.get('nextPageToken')
                if not page_token:
                    break
            
            valid_event_ids = set()
            
            for date_key, items in self.schedule_data.items():
                for item in items:
                    if item.get("type") == "due":
                        event_id = self.generate_event_id(item, date_key)
                        valid_event_ids.add(event_id)
                        dt = datetime.datetime.strptime(date_key, "%Y-%m-%d").date()
                        
                        event_body = {
                            'id': event_id,
                            'summary': f"{item['name']} - {item['drug']} ({item['dosage']})",
                            'description': item.get('memo', ''),
                            'start': {'date': dt.isoformat(), 'timeZone': 'Asia/Seoul'},
                            'end': {'date': dt.isoformat(), 'timeZone': 'Asia/Seoul'},
                        }
                        
                        if event_id in existing_events:
                            service.events().update(calendarId=cal_id, eventId=event_id, body=event_body).execute()
                        else:
                            service.events().insert(calendarId=cal_id, body=event_body).execute()
                            
            for event_id in existing_events:
                if event_id not in valid_event_ids:
                    try:
                        service.events().delete(calendarId=cal_id, eventId=event_id).execute()
                    except HttpError:
                        pass
                                
            if not silent:
                self.root.after(0, lambda: messagebox.showinfo("동기화 완료", "구글 캘린더 연동 및 전체 동기화가 성공적으로 완료되었습니다!"))
                
        except Exception as e:
            if not silent:
                self.root.after(0, lambda: messagebox.showerror("동기화 오류", f"구글 캘린더 동기화 중 오류가 발생했습니다: {str(e)}"))

    def export_to_ics(self):
        cal = Calendar()
        cal.add('prodid', '-//LAI Scheduler//')
        cal.add('version', '2.0')

        for date_key, items in self.schedule_data.items():
            for item in items:
                if item.get("type") == "due":
                    try:
                        event_date = datetime.datetime.strptime(date_key, "%Y-%m-%d").date()
                        event = Event()
                        event.add('summary', f"{item['name']} - {item['drug']} ({item['dosage']})")
                        event.add('dtstart', event_date)
                        event.add('dtend', event_date) # For all-day events, dtend is often the same as dtstart
                        event['X-MICROSOFT-CDO-ALLDAYEVENT'] = 'TRUE'
                        event.add('dtstamp', datetime.datetime.now(pytz.utc))
                        if item.get('memo'):
                            event.add('description', item.get('memo'))
                        
                        # Create a unique ID for the event
                        uid = f'{item.get("record_id", "")}-{date_key}@lai-scheduler'
                        event.add('uid', uid)

                        cal.add_component(event)
                    except (ValueError, KeyError):
                        # Skip malformed date keys or items missing essential keys
                        continue
        return cal.to_ical()

    def open_adherence_dialog(self):
        patients_data = {}
        for date_str, items in self.schedule_data.items():
            for item in items:
                if item.get("type") == "injection":
                    p_name = item.get("name", "").strip()
                    d_name = item.get("drug", "").strip()
                    if p_name and d_name:
                        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                        if p_name not in patients_data:
                            patients_data[p_name] = {}
                        if d_name not in patients_data[p_name]:
                            patients_data[p_name][d_name] = []
                        if dt not in patients_data[p_name][d_name]:
                            patients_data[p_name][d_name].append(dt)
                            
        for p in patients_data:
            for d in patients_data[p]:
                patients_data[p][d].sort()

        if not patients_data:
            messagebox.showinfo("안내", "입력된 주사 처방 기록이 없습니다.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Drug Adherence")
        dialog.geometry("900x700")
        dialog.transient(self.root)
        dialog.grab_set()

        control_frame = tk.LabelFrame(dialog, text=" 조회 옵션 ", font=("맑은 고딕", 10, "bold"), padx=10, pady=10)
        control_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Label(control_frame, text="환자 선택:", font=("맑은 고딕", 9)).grid(row=0, column=0, padx=5, pady=5, sticky="e")
        patient_combo = ttk.Combobox(control_frame, state="readonly", width=15)
        patient_combo.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        
        tk.Label(control_frame, text="약물 선택:", font=("맑은 고딕", 9)).grid(row=0, column=2, padx=5, pady=5, sticky="e")
        drug_combo = ttk.Combobox(control_frame, state="readonly", width=15)
        drug_combo.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        
        tk.Label(control_frame, text="시작일:", font=("맑은 고딕", 9)).grid(row=1, column=0, padx=5, pady=5, sticky="e")
        start_date_combo = ttk.Combobox(control_frame, state="readonly", width=15)
        start_date_combo.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        
        tk.Label(control_frame, text="종료일:", font=("맑은 고딕", 9)).grid(row=1, column=2, padx=5, pady=5, sticky="e")
        end_date_combo = ttk.Combobox(control_frame, state="readonly", width=15)
        end_date_combo.grid(row=1, column=3, padx=5, pady=5, sticky="w")
        
        tk.Label(control_frame, text="주기(일):", font=("맑은 고딕", 9)).grid(row=1, column=4, padx=5, pady=5, sticky="e")
        interval_entry = tk.Entry(control_frame, width=8)
        interval_entry.grid(row=1, column=5, padx=5, pady=5, sticky="w")
        interval_entry.insert(0, "28")

        result_frame = tk.Frame(dialog)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        info_label_var = tk.StringVar()
        pdc_label_var = tk.StringVar()
        
        tk.Label(result_frame, textvariable=info_label_var, font=("맑은 고딕", 10), justify=tk.LEFT).pack(anchor="w", pady=5)
        tk.Label(result_frame, textvariable=pdc_label_var, font=("맑은 고딕", 12, "bold"), fg="#D32F2F", justify=tk.LEFT).pack(anchor="w", pady=5)

        canvas = tk.Canvas(result_frame, bg="white", height=300)
        canvas.pack(fill=tk.BOTH, expand=True, pady=10)

        def update_drugs(event=None):
            p = patient_combo.get()
            if p in patients_data:
                drugs = list(patients_data[p].keys())
                drug_combo["values"] = drugs
                if drugs:
                    drug_combo.current(0)
                    update_dates()
            else:
                drug_combo.set("")
                start_date_combo.set("")
                end_date_combo.set("")

        def update_dates(event=None):
            p = patient_combo.get()
            d = drug_combo.get()
            if p in patients_data and d in patients_data[p]:
                dates_str = [dt.strftime("%Y-%m-%d") for dt in patients_data[p][d]]
                start_date_combo["values"] = dates_str
                end_date_combo["values"] = dates_str
                if dates_str:
                    start_date_combo.current(0)
                    end_date_combo.current(len(dates_str)-1)
            else:
                start_date_combo.set("")
                end_date_combo.set("")

        patient_combo.bind("<<ComboboxSelected>>", update_drugs)
        drug_combo.bind("<<ComboboxSelected>>", update_dates)
        
        patient_list = sorted(list(patients_data.keys()))
        patient_combo["values"] = patient_list
        if patient_list:
            patient_combo.current(0)
            update_drugs()

        def draw_results():
            p = patient_combo.get()
            d = drug_combo.get()
            s_str = start_date_combo.get()
            e_str = end_date_combo.get()
            
            try:
                interval = int(interval_entry.get())
                if interval <= 0: raise ValueError
            except ValueError:
                messagebox.showerror("오류", "올바른 주기를 입력하세요.", parent=dialog)
                return

            if not p or not d or not s_str or not e_str:
                return

            s_date = datetime.datetime.strptime(s_str, "%Y-%m-%d").date()
            e_date = datetime.datetime.strptime(e_str, "%Y-%m-%d").date()

            if s_date > e_date:
                s_date, e_date = e_date, s_date

            valid_dates = [dt for dt in patients_data[p][d] if s_date <= dt <= e_date]
            if not valid_dates:
                info_label_var.set("해당 기간에 주사 기록이 없습니다.")
                pdc_label_var.set("")
                canvas.delete("all")
                return

            total_duration = (e_date - s_date).days
            if total_duration == 0:
                info_label_var.set("시작일과 종료일이 같습니다.")
                pdc_label_var.set("")
                canvas.delete("all")
                return

            total_gap = 0
            total_overlap = 0

            for i in range(len(valid_dates) - 1):
                diff = (valid_dates[i+1] - valid_dates[i]).days
                if diff > interval:
                    total_gap += (diff - interval)
                elif diff < interval:
                    total_overlap += (interval - diff)

            covered_days = total_duration - total_gap
            pdc = (covered_days / total_duration) * 100

            info_label_var.set(f"선택한 전체 기간: {total_duration}일  |  Total Days Late: {total_gap}일")
            pdc_label_var.set(f"PDC(Proportion of Days Covered) = {pdc:.1f}%")

            canvas.delete("all")
            width = canvas.winfo_width()
            height = canvas.winfo_height()
            if width <= 1:
                width = 860 # Fallback
            
            MARGIN_X = 50
            Y_BASE = height // 2
            
            # Baseline
            canvas.create_line(MARGIN_X, Y_BASE, width - MARGIN_X, Y_BASE, fill="#555555", width=4, arrow=tk.BOTH)

            if total_duration > 0:
                pixels_per_day = (width - 2 * MARGIN_X) / total_duration
            else:
                pixels_per_day = 0

            cur_day = 0
            while cur_day <= total_duration:
                x = MARGIN_X + cur_day * pixels_per_day
                canvas.create_line(x, Y_BASE - 10, x, Y_BASE + 10, fill="#555555", width=2)
                tick_date = s_date + datetime.timedelta(days=cur_day)
                canvas.create_text(x, Y_BASE + 20, text=tick_date.strftime("%m-%d"), font=("맑은 고딕", 8), fill="#555555")
                cur_day += interval

            drug_colors = {
                "인베가 서스티나": "#8B0000",
                "인베가 트린자": "#FF8C00",
                "인베가 하피에라": "#90EE90",
                "아빌리파이 메인테나": "#007FFF",
                "아빌리파이 아심투파이": "#008B8B"
            }
            line_color = drug_colors.get(d, "#007FFF")

            layer = 0
            prev_end_day = -1

            for dt in valid_dates:
                start_day = (dt - s_date).days
                end_day = start_day + interval
                
                if start_day < prev_end_day:
                    layer = (layer + 1) % 2
                else:
                    layer = 0

                y_offset = Y_BASE - 15 - (layer * 15)
                
                x1 = MARGIN_X + start_day * pixels_per_day
                x2 = MARGIN_X + end_day * pixels_per_day

                canvas.create_line(x1, y_offset, x2, y_offset, fill=line_color, width=5)
                canvas.create_oval(x1-3, y_offset-3, x1+3, y_offset+3, fill=line_color, outline="white")

                prev_end_day = end_day

        btn_calc = tk.Button(control_frame, text="결과 보기", command=draw_results, bg="#4CAF50", fg="white", font=("맑은 고딕", 9, "bold"))
        btn_calc.grid(row=0, column=6, rowspan=2, padx=15, pady=5, sticky="nsew")

        dialog.after(100, draw_results)

    def sync_ics_file(self):
        sync_path = self.config.get("sync_path")
        if sync_path and os.path.isdir(sync_path):
            ics_data = self.export_to_ics()
            file_path = os.path.join(sync_path, "schedule.ics")
            try:
                with open(file_path, "wb") as f:
                    f.write(ics_data)
                # Optionally, provide feedback to the user
                print(f"Successfully synced to {file_path}")
            except Exception as e:
                print(f"Error syncing ICS file: {e}")
        
    def create_header(self, parent_frame):
        header_frame = tk.Frame(parent_frame)
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        header_frame.columnconfigure(1, weight=1) # Center column expands

        # Otsuka Logo (Left)
        try:
            janssen_img_orig = Image.open("data_image/Otsuka.png")
            janssen_img_resized = janssen_img_orig.resize((150, 40), Image.Resampling.LANCZOS)
            self.janssen_logo = ImageTk.PhotoImage(janssen_img_resized)
            janssen_label = tk.Label(header_frame, image=self.janssen_logo)
            janssen_label.grid(row=0, column=0, sticky="w")
        except FileNotFoundError:
            tk.Label(header_frame, text="Otsuka Logo").grid(row=0, column=0, sticky="w")

        # Navigation (Center)
        nav_frame = tk.Frame(header_frame)
        nav_frame.grid(row=0, column=1, sticky="ew")

        prev_btn = tk.Button(nav_frame, text="◀", command=self.prev_month, font=("맑은 고딕", 12, "bold"))
        prev_btn.pack(side=tk.LEFT, padx=5)

        self.header_label = tk.Label(nav_frame, text=f"{self.year}년 {self.month}월", font=("맑은 고딕", 24, "bold"))
        self.header_label.pack(side=tk.LEFT, expand=True)

        next_btn = tk.Button(nav_frame, text="▶", command=self.next_month, font=("맑은 고딕", 12, "bold"))
        next_btn.pack(side=tk.LEFT, padx=5)

        # Invega Image (Right) - with soft edges
        try:
            img_orig = Image.open("data_image/Abilify_Maintena.jpg")
            img_resized = img_orig.resize((150, 40), Image.Resampling.LANCZOS)
            
            mask = Image.new('L', img_resized.size, 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle((0, 0) + img_resized.size, radius=5, fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(10))

            img_rgba = img_resized.convert("RGBA")
            img_rgba.putalpha(mask)

            self.invega_image = ImageTk.PhotoImage(img_rgba)
            invega_label = tk.Label(header_frame, image=self.invega_image)
            header_bg = header_frame.cget("background")
            invega_label.config(bg=header_bg)
            invega_label.grid(row=0, column=2, sticky="e")

        except FileNotFoundError:
            tk.Label(header_frame, text="Invega Sustenna").grid(row=0, column=2, sticky="e")

        # Weekday Labels
        days_frame = tk.Frame(parent_frame)
        days_frame.grid(row=1, column=0, sticky="ew", padx=10)
        days = ["일", "월", "화", "수", "목", "금", "토"]
        for i, day in enumerate(days):
            days_frame.columnconfigure(i, weight=1)
            color = "red" if i == 0 else "blue" if i == 6 else "black"
            lbl = tk.Label(days_frame, text=day, font=("맑은 고딕", 11, "bold"), fg=color)
            lbl.grid(row=0, column=i, sticky="nsew")

    def create_calendar_frame(self, parent_frame):
        self.calendar_frame = tk.Frame(parent_frame, bg="white")
        self.calendar_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)

    def create_footer(self, parent_frame):
        footer_frame = tk.Frame(parent_frame)
        footer_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5)

        self.show_tomorrow_alarm = tk.BooleanVar(value=True)
        self.show_dat_alarm = tk.BooleanVar(value=True)

        # 구글 캘린더 연동 버튼 추가
        google_sync_btn = tk.Button(footer_frame, text="구글 캘린더 연동", command=self.sync_google_calendar, font=("맑은 고딕", 9, "bold"), bg="#4285F4", fg="white")
        google_sync_btn.pack(side=tk.LEFT, padx=10)

        # Drug Adherence 버튼 추가
        adherence_btn = tk.Button(footer_frame, text="Drug Adherence", command=self.open_adherence_dialog, font=("맑은 고딕", 9, "bold"), bg="#008B8B", fg="white")
        adherence_btn.pack(side=tk.LEFT, padx=5)

        sync_btn = tk.Button(footer_frame, text="ICS 저장 폴더 설정", command=self.set_sync_path, font=("맑은 고딕", 9))
        sync_btn.pack(side=tk.LEFT, padx=5)

        drag_info_label = tk.Label(footer_frame, text="(날짜 이동: Ctrl+클릭 후 드래그)", fg="gray", font=("맑은 고딕", 8))
        drag_info_label.pack(side=tk.LEFT, padx=10)

        cb1 = tk.Checkbutton(footer_frame, text="내일 알림", variable=self.show_tomorrow_alarm, font=("맑은 고딕", 9))
        cb1.pack(side=tk.RIGHT)
        
        cb2 = tk.Checkbutton(footer_frame, text="모레 알림", variable=self.show_dat_alarm, font=("맑은 고딕", 9))
        cb2.pack(side=tk.RIGHT)


    def draw_calendar(self):
        for widget in self.calendar_frame.winfo_children():
            widget.destroy()

        self.day_frames = []
        self.header_label.config(text=f"{self.year}년 {self.month}월")
        cal = calendar.monthcalendar(self.year, self.month)

        for i in range(7):
            self.calendar_frame.columnconfigure(i, weight=1)
        for i in range(len(cal)):
             self.calendar_frame.rowconfigure(i, weight=1)

        today = datetime.date.today()

        for r, week in enumerate(cal):
            for c, day in enumerate(week):
                day_frame = tk.Frame(self.calendar_frame, borderwidth=1, relief="solid", bg="white")
                day_frame.grid(row=r, column=c, sticky="nsew")
                # Store date info in the frame for easy retrieval on drop
                day_frame.date_info = {"year": self.year, "month": self.month, "day": day}
                self.day_frames.append(day_frame)


                if day != 0:
                    date_key = f"{self.year}-{self.month:02d}-{day:02d}"
                    
                    # Day number label
                    day_label_frame = tk.Frame(day_frame, bg='white')
                    day_label_frame.pack(fill='x', padx=3, pady=2)

                    fg_color = "red" if c == 0 else "blue" if c == 6 else "black"
                    day_lbl = tk.Label(day_label_frame, text=str(day), font=("맑은 고딕", 9), fg=fg_color, bg='white')
                    day_lbl.pack(side='left')

                    if self.year == today.year and self.month == today.month and day == today.day:
                        day_frame.config(bg="#FFFFE0")
                        day_label_frame.config(bg="#FFFFE0")
                        day_lbl.config(bg="#FFFFE0")


                    # Appointments frame
                    appointments_frame = tk.Frame(day_frame, bg=day_frame['bg'])
                    appointments_frame.pack(expand=True, fill='both', padx=2, pady=2)
                    
                    day_frame.bind("<Double-Button-1>", lambda e, d=day: self.open_input_dialog(d, None))
                    day_lbl.bind("<Double-Button-1>", lambda e, d=day: self.open_input_dialog(d, None))
                    day_label_frame.bind("<Double-Button-1>", lambda e, d=day: self.open_input_dialog(d, None))
                    appointments_frame.bind("<Double-Button-1>", lambda e, d=day: self.open_input_dialog(d, None))


                    if date_key in self.schedule_data:
                        for item in self.schedule_data[date_key]:
                            block_color = "#D4EDDA" # Completed (injection)
                            is_due = item.get("type") == "due"
                            if is_due:
                                block_color = "#FFDDC1" # Scheduled (due)
                            
                            patient_name = item['name'].split('(')[0]
                            
                            appointment_block = tk.Label(
                                appointments_frame, 
                                text=patient_name, 
                                bg=block_color, 
                                fg="black", 
                                font=("맑은 고딕", 8),
                                relief="solid",
                                borderwidth=1,
                                padx=2,
                                pady=1
                            )
                            appointment_block.pack(fill='x', pady=1)
                            # The lambda captures the current 'item' and 'day' for the handler
                            appointment_block.bind("<Double-Button-1>", lambda e, d=day, i=item: (self.open_input_dialog(d, i), "break"))
                            if is_due:
                                appointment_block.bind("<Control-ButtonPress-1>", lambda e, i=item, w=appointment_block: self.on_drag_start(e, i, w))
                                appointment_block.bind("<B1-Motion>", self.on_drag_motion)
                                appointment_block.bind("<ButtonRelease-1>", self.on_drag_release)

                else:
                    day_frame.config(bg="#F2F2F2", relief='flat')

    def on_drag_start(self, event, item, widget):
        self.drag_item = item
        
        # Hide original widget
        widget.pack_forget()

        # Create a floating drag widget
        self.drag_widget = tk.Toplevel(self.root)
        self.drag_widget.overrideredirect(True)
        self.drag_widget.attributes("-alpha", 0.7)
        self.drag_widget.attributes("-topmost", True)
        
        drag_label = tk.Label(
            self.drag_widget, 
            text=item['name'], 
            bg="#FFDDC1", 
            fg="black", 
            font=("맑은 고딕", 8),
            relief="solid",
            borderwidth=1,
            padx=2,
            pady=1
        )
        drag_label.pack()
        
        self.drag_widget.geometry(f"+{event.x_root}+{event.y_root}")

    def _find_day_frame(self, widget):
        """위젯 트리를 거슬러 올라가 date_info를 가진 day_frame을 반환"""
        w = widget
        while w:
            if hasattr(w, 'date_info'):
                return w
            parent_name = w.winfo_parent()
            if not parent_name or parent_name == '.':
                break
            try:
                w = w.nametowidget(parent_name)
            except KeyError:
                break
        return None

    def _restore_day_frame_bg(self, day_frame):
        """드래그 종료 후 날짜 셀의 원래 배경색으로 복원"""
        today = datetime.date.today()
        di = day_frame.date_info
        if di.get('day', 0) == 0:
            day_frame.config(bg="#F2F2F2")
        elif di['year'] == today.year and di['month'] == today.month and di['day'] == today.day:
            day_frame.config(bg="#FFFFE0")
        else:
            day_frame.config(bg="white")

    def on_drag_motion(self, event):
        if not self.drag_widget:
            return

        x, y = event.x_root, event.y_root
        self.drag_widget.geometry(f"+{x-10}+{y-10}")

        # drag_widget을 잠깐 숨겨서 winfo_containing이 달력 셀을 직접 탐지하도록 함
        # (같은 이벤트 핸들러 내에서는 화면 갱신이 일어나지 않으므로 깜빡임 없음)
        self.drag_widget.withdraw()
        raw_widget = self.root.winfo_containing(x, y)
        self.drag_widget.deiconify()

        day_frame = self._find_day_frame(raw_widget)

        # Reset previous drop target's appearance
        if self.drop_target_frame and self.drop_target_frame != day_frame:
            self._restore_day_frame_bg(self.drop_target_frame)
            self.drop_target_frame = None

        # Highlight new valid drop target
        if day_frame and day_frame.date_info.get('day', 0) != 0:
            day_frame.config(bg="#ADD8E6")  # Light blue highlight
            self.drop_target_frame = day_frame

    def on_drag_release(self, event):
        # If no drag was started, do nothing.
        if not self.drag_item:
            return

        # A drag was in progress, so hide the drag widget
        if self.drag_widget:
            self.drag_widget.destroy()
            self.drag_widget = None

        if self.drop_target_frame and self.drag_item:
            date_info = self.drop_target_frame.date_info
            if date_info['day'] != 0:
                new_date = datetime.date(date_info['year'], date_info['month'], date_info['day'])
                new_date_str = new_date.strftime("%Y-%m-%d")
                
                original_due_date_str = self.drag_item.get('prescribed_date')
                record_id = self.drag_item.get('record_id')

                # Proceed only if the date is different and the item is valid
                if original_due_date_str and new_date_str != original_due_date_str and record_id:
                    # This is an EDIT of the original injection. Find the parent '[injection]' item.
                    parent_injection = None
                    parent_injection_date_str = None
                    for date_key, items in self.schedule_data.items():
                        for item in items:
                            if item.get("record_id") == record_id and item.get("type") == "injection":
                                parent_injection = item
                                parent_injection_date_str = date_key
                                break
                        if parent_injection:
                            break
                    
                    if parent_injection:
                        # 1. Update the parent injection's 'next_date'.
                        parent_injection['next_date'] = new_date_str
                        
                        # 2. Recalculate and update the interval for both records.
                        injection_date = datetime.datetime.strptime(parent_injection_date_str, "%Y-%m-%d").date()
                        new_interval = (new_date - injection_date).days
                        parent_injection['interval'] = new_interval
                        self.drag_item['interval'] = new_interval # Update the item being dragged

                        # 3. Move the '[due]' item (self.drag_item) to the new date.
                        source_list = self.schedule_data.get(original_due_date_str, [])
                        if self.drag_item in source_list:
                            source_list.remove(self.drag_item)
                            if not source_list:
                                del self.schedule_data[original_due_date_str]

                        if new_date_str not in self.schedule_data:
                            self.schedule_data[new_date_str] = []
                        self.drag_item['prescribed_date'] = new_date_str
                        self.schedule_data[new_date_str].append(self.drag_item)
                        
                        self.save_data()

        # Reset drag variables and redraw the calendar
        self.drag_item = None
        self.drop_target_frame = None
        self.draw_calendar()
        
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

    def open_input_dialog(self, day, item=None):
        target_date = datetime.date(self.year, self.month, day)
        date_key = target_date.strftime("%Y-%m-%d")
        
        is_new_record = item is None
        is_due_item = not is_new_record and item.get("type") == "due"
        is_injection_item = not is_new_record and item.get("type") == "injection"

        dialog = tk.Toplevel(self.root)
        dialog.title(f"기록 관리: {date_key}")
        dialog.geometry("450x700")
        dialog.transient(self.root)
        dialog.grab_set()


        # Determine mode and title
        if is_new_record:
            frame_title = " [신규 처방 입력] "
        elif is_due_item:
            frame_title = " [예약 환자 처방] "
        else: # is_injection_item
            frame_title = " [처방 기록 수정] "

        input_frame = tk.LabelFrame(dialog, text=frame_title, font=("맑은 고딕", 11, "bold"), padx=10, pady=10)
        input_frame.pack(fill=tk.X, padx=10, pady=10)

        # 1. Patient Name (Top)
        name_frame = tk.Frame(input_frame)
        name_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(name_frame, text="환자명: ", font=("맑은 고딕", 9, "bold")).pack(side=tk.LEFT)
        name_entry = tk.Entry(name_frame, width=20, font=("맑은 고딕", 9))
        name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 2. Dynamic Injections Frame
        injections_lbl_frame = tk.Frame(input_frame)
        injections_lbl_frame.pack(fill=tk.X, pady=(0, 5))
        tk.Label(injections_lbl_frame, text="처방 목록:", font=("맑은 고딕", 9, "bold")).pack(side=tk.LEFT)
        
        injections_container = tk.Frame(input_frame)
        injections_container.pack(fill=tk.X, pady=(0, 10))

        drug_rows = []

        def add_drug_row(drug_val="", dosage_val="", interval_val="28"):
            row_frame = tk.Frame(injections_container, bd=1, relief="ridge", padx=5, pady=5)
            row_frame.pack(fill=tk.X, pady=4)
            
            top_sub_frame = tk.Frame(row_frame)
            top_sub_frame.pack(fill=tk.X)
            
            bot_sub_frame = tk.Frame(row_frame)
            bot_sub_frame.pack(fill=tk.X, pady=(4, 0))
            
            drug_combo = ttk.Combobox(top_sub_frame, values=list(DRUG_DATABASE.keys()), state="readonly", width=25)
            drug_combo.pack(side=tk.LEFT)
            
            def remove_row():
                if len(drug_rows) > 1:
                    row_frame.destroy()
                    drug_rows.remove(row_data)
            
            del_btn = tk.Button(top_sub_frame, text=" 삭제 ", command=remove_row, fg="red", font=("맑은 고딕", 8, "bold"), padx=2, pady=0)
            del_btn.pack(side=tk.RIGHT)

            tk.Label(bot_sub_frame, text="용량:", font=("맑은 고딕", 9)).pack(side=tk.LEFT)
            dosage_combo = ttk.Combobox(bot_sub_frame, state="readonly", width=12)
            dosage_combo.pack(side=tk.LEFT, padx=2)
            
            # Spacer
            tk.Label(bot_sub_frame, text="    ").pack(side=tk.LEFT)

            tk.Label(bot_sub_frame, text="간격:", font=("맑은 고딕", 9)).pack(side=tk.LEFT, padx=2)
            interval_entry = tk.Entry(bot_sub_frame, width=5)
            interval_entry.pack(side=tk.LEFT, padx=2)
            tk.Label(bot_sub_frame, text="일", font=("맑은 고딕", 9)).pack(side=tk.LEFT)
            
            def on_drug_select(event, d_combo=drug_combo, dos_combo=dosage_combo):
                selected_drug = d_combo.get()
                dosages = DRUG_DATABASE.get(selected_drug, [])
                dos_combo["values"] = dosages
                if dosages:
                    dos_combo.current(0)
                else:
                    dos_combo.set("")
            
            drug_combo.bind("<<ComboboxSelected>>", on_drug_select)
            
            row_data = {
                'frame': row_frame,
                'drug': drug_combo,
                'dosage': dosage_combo,
                'interval': interval_entry
            }
            
            if drug_val:
                drug_combo.set(drug_val)
                dosages = DRUG_DATABASE.get(drug_val, [])
                dosage_combo["values"] = dosages
                if dosage_val in dosages:
                    dosage_combo.set(dosage_val)
                elif dosages:
                    dosage_combo.current(0)
            else:
                drug_combo.current(0)
                on_drug_select(None, drug_combo, dosage_combo)
                
            interval_entry.insert(0, str(interval_val))
            drug_rows.append(row_data)

        # "Add Injection" button
        add_row_btn = tk.Button(injections_lbl_frame, text="+ 주사 항목 추가", command=lambda: add_drug_row(), font=("맑은 고딕", 8))
        add_row_btn.pack(side=tk.RIGHT)

        # 3. Memo
        memo_frame = tk.Frame(input_frame)
        memo_frame.pack(fill=tk.X, pady=(0, 5))
        tk.Label(memo_frame, text="메모:", font=("맑은 고딕", 9, "bold")).pack(anchor=tk.W)
        memo_text = tk.Text(memo_frame, height=3, width=28, font=("맑은 고딕", 9))
        memo_text.pack(fill=tk.X)

        # Populate fields if editing or completing
        if not is_new_record:
            name_entry.insert(0, item.get("name", ""))
            add_drug_row(item.get("drug", ""), item.get("dosage", ""), item.get("interval", "28"))
            memo_text.insert("1.0", item.get("memo", ""))
        else:
            add_drug_row()

        def save_action():
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("오류", "환자명을 입력해주세요.", parent=dialog)
                return
            
            parsed_rows = []
            for r in drug_rows:
                drug_val = r['drug'].get()
                dosage_val = r['dosage'].get()
                try:
                    interval_val = int(r['interval'].get())
                except ValueError:
                    messagebox.showerror("오류", "간격은 숫자만 입력해주세요.", parent=dialog)
                    return
                parsed_rows.append({
                    "drug": drug_val,
                    "dosage": dosage_val,
                    "interval": interval_val
                })

            base_new_data = {
                "name": name,
                "memo": memo_text.get("1.0", tk.END).strip(),
            }

            next_dates_strs = []

            for i, row_data in enumerate(parsed_rows):
                new_data = base_new_data.copy()
                new_data.update(row_data)
                
                # Treat first row as the item being edited, subsequent rows as new records
                current_is_new = is_new_record if i == 0 else True
                current_is_due = is_due_item if i == 0 else False
                current_is_inj = is_injection_item if i == 0 else False
                
                # Case 1: New record OR Completing a 'due' item
                if current_is_new or current_is_due:
                    record_id = int(time.time() * 1000) + i # ensure unique id

                    # If completing a 'due' item, first remove the old record
                    if current_is_due:
                        old_due_date_str = item["prescribed_date"]
                        old_record_id = item.get("record_id")

                        # Find and remove the specific 'due' item
                        item_to_remove = next((x for x in self.schedule_data.get(old_due_date_str, []) if x.get("record_id") == old_record_id), None)
                        if item_to_remove:
                            self.schedule_data[old_due_date_str].remove(item_to_remove)
                            if not self.schedule_data[old_due_date_str]:
                                del self.schedule_data[old_due_date_str]

                        # 연결된 이전 주사(injection) 기록의 간격과 next_date를 실제 주사일 기준으로 업데이트
                        injection_date_str_actual = target_date.strftime("%Y-%m-%d")
                        for date_key_itr, records in self.schedule_data.items():
                            for rec in records:
                                if rec.get("record_id") == old_record_id and rec.get("type") == "injection":
                                    parent_inj_date = datetime.datetime.strptime(date_key_itr, "%Y-%m-%d").date()
                                    actual_interval = (target_date - parent_inj_date).days
                                    rec["interval"] = actual_interval
                                    rec["next_date"] = injection_date_str_actual
                                    break
                    
                    injection_date = target_date
                    injection_date_str = injection_date.strftime("%Y-%m-%d")
                    next_date = injection_date + datetime.timedelta(days=row_data["interval"])
                    next_date_str = next_date.strftime("%Y-%m-%d")
                    next_dates_strs.append(next_date_str)

                    injection_record = new_data.copy()
                    injection_record.update({
                        "record_id": record_id,
                        "type": "injection",
                        "prescribed_date": injection_date_str,
                        "next_date": next_date_str,
                    })
                    if injection_date_str not in self.schedule_data: self.schedule_data[injection_date_str] = []
                    self.schedule_data[injection_date_str].append(injection_record)

                    due_record = new_data.copy()
                    due_record.update({
                        "record_id": record_id,
                        "type": "due",
                        "prescribed_date": next_date_str,
                        "next_date": None,
                    })
                    if next_date_str not in self.schedule_data: self.schedule_data[next_date_str] = []
                    self.schedule_data[next_date_str].append(due_record)

                # Case 2: Editing an existing 'injection' record
                elif current_is_inj:
                    record_id = item.get("record_id")
                    original_prescribed_date = item.get("prescribed_date")

                    item.update(new_data)
                    
                    new_next_date = datetime.datetime.strptime(original_prescribed_date, "%Y-%m-%d").date() + datetime.timedelta(days=row_data["interval"])
                    new_next_date_str = new_next_date.strftime("%Y-%m-%d")
                    item["next_date"] = new_next_date_str
                    next_dates_strs.append(new_next_date_str)

                    due_item_to_update = None
                    due_item_date_str = None
                    for dk, recs in self.schedule_data.items():
                        for rec in recs:
                            if rec.get("record_id") == record_id and rec.get("type") == "due":
                                due_item_to_update = rec
                                due_item_date_str = dk
                                break
                        if due_item_to_update: break

                    if due_item_to_update:
                        self.schedule_data[due_item_date_str].remove(due_item_to_update)
                        if not self.schedule_data[due_item_date_str]:
                            del self.schedule_data[due_item_date_str]
                        due_item_to_update.update(new_data)
                        due_item_to_update["prescribed_date"] = new_next_date_str
                        if new_next_date_str not in self.schedule_data:
                            self.schedule_data[new_next_date_str] = []
                        self.schedule_data[new_next_date_str].append(due_item_to_update)
                    else:
                        new_due = new_data.copy()
                        new_due.update({
                            "record_id": record_id,
                            "type": "due",
                            "prescribed_date": new_next_date_str,
                            "next_date": None,
                        })
                        if new_next_date_str not in self.schedule_data:
                            self.schedule_data[new_next_date_str] = []
                        self.schedule_data[new_next_date_str].append(new_due)

            messagebox.showinfo("성공", f"저장/수정되었습니다.\n다음 예정일(들):\n" + "\n".join(next_dates_strs), parent=dialog)
            self.save_data()
            dialog.destroy()
            self.draw_calendar()

        button_frame = tk.Frame(input_frame)
        button_frame.pack(fill=tk.X, pady=10)

        # Unified Save/Modify Button
        btn_text = "등록/수정"
        save_btn = tk.Button(button_frame, text=btn_text, command=save_action, bg="#4CAF50", fg="white", font=("맑은 고딕", 10, "bold"))
        save_btn.pack(fill=tk.X)


        list_frame = tk.LabelFrame(dialog, text=f" [ {date_key} 기록 목록 ] ", font=("맑은 고딕", 11, "bold"), padx=10, pady=10)
        list_frame.pack(fill=tk.X, padx=10, pady=5)

        scrollable_frame = tk.Frame(list_frame)
        scrollable_frame.pack(fill=tk.X)

        current_items = self.schedule_data.get(date_key, [])
        if not current_items:
            tk.Label(scrollable_frame, text="기록된 내역이 없습니다.", fg="gray").pack(pady=20)
        else:
            for loop_item in current_items:
                item_frame = tk.Frame(scrollable_frame, relief="groove", borderwidth=1, pady=5)
                item_frame.pack(fill=tk.X, pady=2, padx=2)

                type_text = "[주사]" if loop_item.get("type") == "injection" else "[예정]"
                type_color = "blue" if loop_item.get("type") == "injection" else "red"
                memo_content = loop_item.get("memo", "")
                memo_display = f"\n메모: {memo_content}" if memo_content else ""
                info_text = f"{type_text} {loop_item['name']}\n{loop_item['drug']} ({loop_item['dosage']}){memo_display}"

                lbl = tk.Label(item_frame, text=info_text, justify=tk.LEFT, fg=type_color, font=("맑은 고딕", 9))
                lbl.pack(side=tk.LEFT, padx=5)

                def delete_item(item_to_delete):
                    is_injection = item_to_delete.get("type") == "injection"
                    if is_injection:
                        confirm_msg = "정말 이 주사 기록을 삭제하시겠습니까?\n(연결된 다음 예약도 함께 삭제됩니다)"
                    else:
                        confirm_msg = "정말 이 예약을 삭제하시겠습니까?\n(이전 주사 기록은 유지됩니다)"
                    if not messagebox.askyesno("삭제 확인", confirm_msg, parent=dialog):
                        return

                    current_date_key = item_to_delete["prescribed_date"]

                    # Remove the item itself
                    item_to_remove = next((i for i in self.schedule_data.get(current_date_key, []) if i == item_to_delete), None)
                    if item_to_remove:
                        self.schedule_data[current_date_key].remove(item_to_remove)
                        if not self.schedule_data[current_date_key]: del self.schedule_data[current_date_key]

                    # 주사 기록 삭제 시 → 연결된 예약(due)도 함께 삭제
                    if is_injection and "record_id" in item_to_delete:
                        record_id = item_to_delete["record_id"]
                        next_date_str = item_to_delete.get("next_date")
                        if next_date_str and next_date_str in self.schedule_data:
                            self.schedule_data[next_date_str] = [i for i in self.schedule_data[next_date_str] if i.get("record_id") != record_id]
                            if not self.schedule_data[next_date_str]: del self.schedule_data[next_date_str]

                    # 예약(due) 삭제 시 → 해당 예약만 삭제, 이전 주사 기록은 유지
                    # (injection은 실제로 맞은 기록이므로 삭제하지 않음)
                    
                    self.save_data()
                    dialog.destroy()
                    self.draw_calendar()

                del_btn = tk.Button(item_frame, text="삭제", bg="#FFCDD2", command=lambda i=loop_item: delete_item(i))
                del_btn.pack(side=tk.RIGHT, padx=5)

        def auto_resize_dialog():
            dialog.update_idletasks()
            req_h = dialog.winfo_reqheight()
            screen_h = dialog.winfo_screenheight()
            new_h = min(req_h + 20, screen_h - 80)
            if new_h > 700:
                dialog.geometry(f"450x{new_h}")

        dialog.after(50, auto_resize_dialog)


    def start_notification_thread(self):
        t = threading.Thread(target=self.notification_loop, daemon=True)
        t.start()

    def notification_loop(self):
        while True:
            now = datetime.datetime.now()
            today = now.date()

            # 매일 오전 7시 이후에 하루에 한 번만 알림을 확인합니다.
            if now.hour >= 7 and self.last_notification_check_date != today:
                self.root.after(0, self.check_and_notify)

            # 10분마다 루프를 실행하여 날짜 변경을 확인합니다.
            time.sleep(600)

    def check_and_notify(self, manual_check=False):
        with self.notification_lock:
            today = datetime.date.today()
            
            # If not a manual check and we've already checked today, do nothing.
            if not manual_check and self.last_notification_check_date == today:
                return
            
            # D-Day (오늘)
            today_str = today.strftime("%Y-%m-%d")
            if today_str in self.schedule_data:
                items = [f"● {item['name']} - {item['drug']} {item['dosage']}" for item in self.schedule_data[today_str] if item.get("type") == "due"]
                if items:
                    self.show_custom_notification("오늘 예정 환자", "\n".join(items), "today")

            # D+1 (내일)
            tmr_str = ""
            if self.show_tomorrow_alarm.get():
                tmr = today + datetime.timedelta(days=1)
                tmr_str = tmr.strftime("%Y-%m-%d")
                if tmr_str in self.schedule_data:
                    items = [f"○ {item['name']} - {item['drug']} {item['dosage']}" for item in self.schedule_data[tmr_str] if item.get("type") == "due"]
                    if items:
                        self.show_custom_notification("내일 예정 환자", "\n".join(items), "tomorrow")

            # D+2 (모레)
            dat_str = ""
            if self.show_dat_alarm.get():
                dat = today + datetime.timedelta(days=2)
                dat_str = dat.strftime("%Y-%m-%d")
                if dat_str in self.schedule_data:
                    items = [f"○ {item['name']} - {item['drug']} {item['dosage']}" for item in self.schedule_data[dat_str] if item.get("type") == "due"]
                    if items:
                        self.show_custom_notification("모레 예정 환자", "\n".join(items), "dat")

            if manual_check:
                had_today = any(i.get("type") == "due" for i in self.schedule_data.get(today_str, []))
                had_tomorrow = self.show_tomorrow_alarm.get() and any(i.get("type") == "due" for i in self.schedule_data.get(tmr_str, []))
                had_dat = self.show_dat_alarm.get() and any(i.get("type") == "due" for i in self.schedule_data.get(dat_str, []))
                
                if not (had_today or had_tomorrow or had_dat):
                    messagebox.showinfo("알림 없음", "활성화된 알림 설정에 해당하는 예정된 주사 환자가 없습니다.")
            
            # If we performed a check, record the date to prevent re-checking today.
            if not manual_check:
                self.last_notification_check_date = today


    def show_custom_notification(self, title, message, level):
        level_configs = {
            "today": {"bg": "#FFEBEE", "header_bg": "#E91E63", "title": "📢 [오늘] ", "offset": 0},
            "tomorrow": {"bg": "#FFF3E0", "header_bg": "#FF9800", "title": "🔔 [내일] ", "offset": 260},
            "dat": {"bg": "#E3F2FD", "header_bg": "#2196F3", "title": "ℹ️ [모레] ", "offset": 520},
        }
        config = level_configs.get(level, level_configs["tomorrow"])

        popup = tk.Toplevel(self.root)
        popup.title("알림")
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)

        TRANSP = "#010101"
        popup.configure(bg=TRANSP)
        try:
            popup.attributes("-transparentcolor", TRANSP)
        except Exception:
            popup.configure(bg=config["bg"])

        screen_width = popup.winfo_screenwidth()
        screen_height = popup.winfo_screenheight()

        window_width = 330
        window_height = 240
        x_pos = screen_width - window_width - 20
        y_pos = screen_height - window_height - 50 - config["offset"]

        popup.geometry(f"{window_width}x{window_height}+{x_pos}+{y_pos}")

        RADIUS = 13
        BORDER = 2

        canvas = tk.Canvas(popup, width=window_width, height=window_height,
                           bg=TRANSP, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        def _rrect(x1, y1, x2, y2, r):
            return [
                x1+r, y1, x2-r, y1,
                x2, y1, x2, y1+r,
                x2, y2-r, x2, y2,
                x2-r, y2, x1+r, y2,
                x1, y2, x1, y2-r,
                x1, y1+r, x1, y1,
            ]

        canvas.create_polygon(_rrect(0, 0, window_width, window_height, RADIUS),
                              smooth=True, fill=config["header_bg"], outline="")
        canvas.create_polygon(_rrect(BORDER, BORDER, window_width-BORDER, window_height-BORDER, RADIUS-1),
                              smooth=True, fill=config["bg"], outline="")

        pad = BORDER + 3
        content_w = window_width - 2 * pad
        content_h = window_height - 2 * pad
        content_frame = tk.Frame(canvas, bg=config["bg"], width=content_w, height=content_h)
        content_frame.pack_propagate(False)
        canvas.create_window(pad, pad, anchor="nw", window=content_frame,
                             width=content_w, height=content_h)

        tk.Label(
            content_frame,
            text=config["title"] + title,
            bg=config["header_bg"],
            fg="white",
            font=("맑은 고딕", 11, "bold"),
            pady=7,
        ).pack(fill=tk.X)

        tk.Label(
            content_frame,
            text=message,
            bg=config["bg"],
            font=("맑은 고딕", 10),
            justify=tk.LEFT,
            padx=12,
            pady=8,
            wraplength=content_w - 20,
        ).pack(expand=True, fill=tk.BOTH)

        def close_popup():
            self.open_popups[level] = None
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", close_popup)
        self.open_popups[level] = popup

        tk.Button(
            content_frame, text="확인 (창 닫기)", command=close_popup,
            bg="white", borderwidth=1
        ).pack(pady=8)

    def _close_one_popup(self, event=None):
        """Alt+K: 모레→내일→오늘 순서로 팝업 하나씩 닫기"""
        for level in ("dat", "tomorrow", "today"):
            popup = self.open_popups.get(level)
            if popup and popup.winfo_exists():
                self.open_popups[level] = None
                popup.destroy()
                return

    def _close_all_popups(self, event=None):
        """Shift+Alt+K: 열린 알림 팝업 모두 닫기"""
        for level in ("dat", "tomorrow", "today"):
            popup = self.open_popups.get(level)
            if popup and popup.winfo_exists():
                self.open_popups[level] = None
                popup.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = LAI_Scheduler_App(root)
    root.mainloop()
