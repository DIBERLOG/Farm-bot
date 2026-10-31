#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use eframe::egui::{self, Color32, RichText, Vec2};
use serde_json::{Value, json};
mod animation;
mod statistics;
use animation::{Animation, Motion};
use std::os::windows::process::CommandExt;
use std::{
    collections::VecDeque,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::mpsc,
    time::Duration,
};
const MINT: Color32 = Color32::from_rgb(106, 224, 182);
const MUTED: Color32 = Color32::from_rgb(151, 167, 183);
const PANEL: Color32 = Color32::from_rgb(20, 35, 39);
fn card() -> egui::Frame {
    egui::Frame::new()
        .fill(PANEL)
        .corner_radius(10)
        .stroke(egui::Stroke::new(1_f32, Color32::from_rgb(43, 76, 69)))
        .inner_margin(20.)
}
fn mint_card(ui: &mut egui::Ui, contents: impl FnOnce(&mut egui::Ui)) {
    let background = ui.painter().add(egui::Shape::Noop);
    let response = card().fill(Color32::TRANSPARENT).corner_radius(0).show(ui, contents);
    let rect = response.response.rect;
    let time = ui.input(|input| input.time) as f32;
    let animate = ui.style().animation_time > 0.;
    let phase = if animate { time * 0.35 } else { 0. };
    let mut mesh = egui::Mesh::default();
    for index in 0..=32 {
        let fraction = index as f32 / 32.;
        let glow = ((fraction * 5. - phase).sin() + 1.) * 0.5;
        let color = Color32::from_rgb((20. + glow * 12.) as u8,
            (43. + glow * 30.) as u8, (39. + glow * 23.) as u8);
        let x = egui::lerp(rect.x_range(), fraction);
        mesh.colored_vertex(egui::pos2(x, rect.top()), color);
        mesh.colored_vertex(egui::pos2(x, rect.bottom()), Color32::from_rgb(17, 32, 30));
        if index < 32 {
            let start = index * 2;
            mesh.add_triangle(start, start + 1, start + 2);
            mesh.add_triangle(start + 1, start + 3, start + 2);
        }
    }
    ui.painter().set(background, egui::Shape::mesh(mesh));
}
const RESOURCES: [&str; 4] = ["Ферма", "Нефть", "Шахта", "Не отправлять"];
const MATERIALS: [&str; 6] = [
    "Доска",
    "Кирпич",
    "Цемент",
    "Железная балка",
    "Асфальт",
    "Бетон",
];

struct Helper {
    root: PathBuf,
    child: Option<Child>,
    input: Option<ChildStdin>,
    events: mpsc::Receiver<Value>,
    page: usize,
    ready: bool,
    busy: bool,
    closing: bool,
    hidden: bool,
    repeat: bool,
    join_army_groups: bool,
    status: String,
    error: String,
    notice: String,
    logs: VecDeque<String>,
    plan: Vec<String>,
    production: Value,
    statistics: Value,
    pending_start: Option<String>,
    dirty: bool,
    emergency_enabled: bool,
    emergency_key: String,
    emergency_has_key: bool,
    rescue_x: u32,
    rescue_y: u32,
    rescue_destination: bool,
    steps: Vec<(String, String)>,
    character: usize,
    animation: Animation,
    animation_test: bool,
    poses: [Option<egui::TextureHandle>; 3],
    alternate_poses: [Option<egui::TextureHandle>; 2],
    operator: Option<egui::TextureHandle>,
    operator_salute: Option<egui::TextureHandle>,
    campaign_sea: bool,
    campaign_note: String,
    greeting_until: f64,
    crew: Option<egui::TextureHandle>,
    crew_blink: Option<egui::TextureHandle>,
    crew_salute: Option<egui::TextureHandle>,
}
fn root_dir() -> PathBuf {
    let exe = std::env::current_exe().unwrap_or_default();
    let parent = exe.parent().unwrap_or(std::path::Path::new("."));
    if parent.join("worker.py").exists() {
        parent.to_owned()
    } else {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_owned()
    }
}
impl Helper {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        cc.egui_ctx.set_theme(egui::Theme::Dark);
        let mut fonts = egui::FontDefinitions::default();
        fonts.font_data.insert(
            "Golos".into(),
            egui::FontData::from_static(include_bytes!("../assets/GolosText.ttf")).into(),
        );
        fonts
            .families
            .get_mut(&egui::FontFamily::Proportional)
            .unwrap()
            .insert(0, "Golos".into());
        cc.egui_ctx.set_fonts(fonts);
        let mut style = (*cc.egui_ctx.style()).clone();
        style.visuals = egui::Visuals::dark();
        style.visuals.panel_fill = Color32::from_rgb(16, 23, 33);
        style.visuals.window_fill = Color32::from_rgb(24, 34, 47);
        style.visuals.extreme_bg_color = Color32::from_rgb(11, 17, 25);
        style.visuals.selection.bg_fill = Color32::from_rgb(39, 88, 76);
        style.visuals.widgets.inactive.bg_fill = Color32::from_rgb(32, 46, 62);
        style.visuals.widgets.hovered.bg_fill = Color32::from_rgb(47, 68, 87);
        style.visuals.widgets.inactive.corner_radius = egui::CornerRadius::same(7);
        style.visuals.widgets.hovered.corner_radius = egui::CornerRadius::same(7);
        style.visuals.widgets.active.corner_radius = egui::CornerRadius::same(7);
        style.visuals.widgets.active.bg_fill = Color32::from_rgb(40, 100, 84);
        style.visuals.selection.stroke = egui::Stroke::new(1_f32, MINT);
        style.spacing.item_spacing = Vec2::new(12., 12.);
        style.spacing.button_padding = Vec2::new(15., 11.);
        style.spacing.interact_size.y = 36.;
        style
            .text_styles
            .insert(egui::TextStyle::Body, egui::FontId::proportional(16.));
        style
            .text_styles
            .insert(egui::TextStyle::Button, egui::FontId::proportional(16.));
        cc.egui_ctx.set_style(style);
        let (tx, events) = mpsc::channel();
        let root = root_dir();
        let python = PathBuf::from(std::env::var("LOCALAPPDATA").unwrap_or_default())
            .join("Programs/Python/Python314/python.exe");
        let pose_assets: [(&str, &[u8]); 3] = [
            ("operator-poses", include_bytes!("../assets/operator-poses.png")),
            ("mechanic-poses", include_bytes!("../assets/mechanic-poses.png")),
            ("officer-poses", include_bytes!("../assets/officer-poses.png")),
        ];
        let alternate_assets: [(&str, &[u8]); 2] = [
            ("mechanic-alternate", include_bytes!("../assets/mechanic-poses-alt.png")),
            ("officer-alternate", include_bytes!("../assets/officer-poses-alt.png")),
        ];
        let mut app = Self {
            alternate_poses: alternate_assets.map(|(name, bytes)| eframe::icon_data::from_png_bytes(bytes).ok().map(|icon|
                cc.egui_ctx.load_texture(name, egui::ColorImage::from_rgba_unmultiplied(
                    [icon.width as usize, icon.height as usize], &icon.rgba), egui::TextureOptions::NEAREST))),
            animation: Animation::default(),
            animation_test: std::env::args().any(|arg| arg == "--animation-check"),
            poses: pose_assets.map(|(name, bytes)| eframe::icon_data::from_png_bytes(bytes).ok().map(|icon|
                cc.egui_ctx.load_texture(name, egui::ColorImage::from_rgba_unmultiplied(
                    [icon.width as usize, icon.height as usize], &icon.rgba), egui::TextureOptions::NEAREST))),
            character: std::fs::read_to_string(root.join("character.txt")).ok().and_then(|value| value.trim().parse::<usize>().ok()).filter(|value| *value < 3).unwrap_or(0),
            root: root.clone(),
            child: None,
            input: None,
            events,
            page: if std::env::args().any(|a|a=="--statistics-page") {5} else {0},
            ready: false,
            busy: false,
            closing: false,
            hidden: false,
            repeat: true,
            join_army_groups: false,
            status: "Подключение помощника…".into(),
            error: String::new(),
            notice: String::new(),
            logs: VecDeque::new(),
            plan: vec![],
            production: Value::Null,
            statistics: Value::Null,
            pending_start: None,
            dirty: false,
            emergency_enabled: false,
            emergency_key: String::new(),
            emergency_has_key: false,
            rescue_x: 0,
            rescue_y: 0,
            rescue_destination: false,
            steps: Vec::new(),
            campaign_sea: false,
            campaign_note: String::new(),
            greeting_until: 0.,
            crew_blink: eframe::icon_data::from_png_bytes(include_bytes!("../assets/crew-blink.png")).ok().map(|icon| cc.egui_ctx.load_texture("crew-blink", egui::ColorImage::from_rgba_unmultiplied([icon.width as usize, icon.height as usize], &icon.rgba), egui::TextureOptions::NEAREST)),
            crew_salute: eframe::icon_data::from_png_bytes(include_bytes!("../assets/crew-salute.png")).ok().map(|icon| cc.egui_ctx.load_texture("crew-salute", egui::ColorImage::from_rgba_unmultiplied([icon.width as usize, icon.height as usize], &icon.rgba), egui::TextureOptions::NEAREST)),
            crew: eframe::icon_data::from_png_bytes(include_bytes!("../assets/crew.png")).ok().map(|icon| cc.egui_ctx.load_texture("crew", egui::ColorImage::from_rgba_unmultiplied([icon.width as usize, icon.height as usize], &icon.rgba), egui::TextureOptions::NEAREST)),
            operator_salute: eframe::icon_data::from_png_bytes(include_bytes!("../assets/operator-salute.png")).ok().map(|icon| cc.egui_ctx.load_texture("operator-salute", egui::ColorImage::from_rgba_unmultiplied([icon.width as usize, icon.height as usize], &icon.rgba), egui::TextureOptions::NEAREST)),
            operator: eframe::icon_data::from_png_bytes(include_bytes!("../assets/operator.png")).ok().map(|icon| {
                cc.egui_ctx.load_texture("operator", egui::ColorImage::from_rgba_unmultiplied(
                    [icon.width as usize, icon.height as usize], &icon.rgba), egui::TextureOptions::NEAREST)
            }),
        };
        if app.animation_test {
            app.status = "Проверка анимаций · игра не изменяется".into();
            return app;
        }
        match Command::new(python)
            .arg("-u")
            .arg(root.join("worker.py"))
            .current_dir(&root)
            .creation_flags(0x08000000)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(mut child) => {
                app.input = child.stdin.take();
                let stdout = child.stdout.take().unwrap();
                let stderr = child.stderr.take().unwrap();
                let errors = tx.clone();
                std::thread::spawn(move || {
                    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                        let event=serde_json::from_str::<Value>(&line).unwrap_or_else(|_|json!({"event":"error","message":"Некорректный ответ рабочего процесса"}));
                        if tx.send(event).is_err() {
                            break;
                        }
                    }
                });
                std::thread::spawn(move || {
                    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                        if errors
                            .send(json!({"event":"error","message":line}))
                            .is_err()
                        {
                            break;
                        }
                    }
                });
                app.child = Some(child);
            }
            Err(e) => {
                app.status = "Не удалось запустить помощника".into();
                app.error = e.to_string();
            }
        }
        app
    }
    fn send(&mut self, value: Value) {
        let result = self
            .input
            .as_mut()
            .ok_or_else(|| "Рабочий процесс недоступен".to_string())
            .and_then(|input| {
                writeln!(input, "{value}")
                    .and_then(|_| input.flush())
                    .map_err(|e| e.to_string())
            });
        if let Err(error) = result {
            self.error = error;
            self.pending_start = None;
        }
    }
    fn save(&mut self) {
        self.notice.clear();
        self.error.clear();
        self.send(json!({"command":"save","plan":self.plan,"production":self.production}));
    }
    fn start(&mut self, task: &str) {
        if self.busy || !self.ready || self.pending_start.is_some() {
            return;
        }
        self.greeting_until = -1.;
        self.pending_start = Some(task.into());
        self.steps.clear();
        self.save();
    }
    fn poll(&mut self, now: f64) {
        while let Ok(event) = self.events.try_recv() {
            let message = event["message"].as_str().unwrap_or("").to_owned();
            match event["event"].as_str().unwrap_or("") {
                "ready" => {
                    self.send(json!({"command":"statistics"}));
                    self.join_army_groups = event["army_groups"].as_bool().unwrap_or(false);
                    self.rescue_x = event["emergency"]["x"].as_u64().unwrap_or(0) as u32;
                    self.rescue_y = event["emergency"]["y"].as_u64().unwrap_or(0) as u32;
                    self.rescue_destination = event["emergency"]["destination_set"]
                        .as_bool()
                        .unwrap_or(false);
                    self.emergency_enabled =
                        event["emergency"]["enabled"].as_bool().unwrap_or(false);
                    self.emergency_has_key =
                        event["emergency"]["has_key"].as_bool().unwrap_or(false);
                    if let Ok(plan) = serde_json::from_value::<Vec<String>>(event["plan"].clone()) {
                        if plan.len() == 5
                            && event["production"]["workshops"]
                                .as_array()
                                .is_some_and(|a| a.len() == 4)
                        {
                            self.plan = plan;
                            self.production = event["production"].clone();
                            self.ready = true;
                            self.status = "Готов к запуску".into();
                            if std::env::args().any(|a| a == "--auto-farm") {
                                self.start("cycle");
                            }
                        } else {
                            self.error = "Не удалось прочитать схемы".into();
                        }
                    }
                }
                "saved" => {
                    self.dirty = false;
                    self.notice = message;
                    if let Some(task) = self.pending_start.take() {
                        self.busy = true;
                        self.status = "Запуск…".into();
                        self.send(json!({"command":"start","task":task,"repeat":self.repeat}));
                    }
                }
                "animation" => {
                    if let Some(motion) = event["state"].as_str().and_then(Motion::parse) {
                        self.animation.receive(motion, now);
                    }
                }
                "statistics" => {
                    self.statistics=event["data"].clone();
                    if self.error.starts_with("Статистика временно недоступна")
                        || self.error.starts_with("Expecting property name enclosed in double quotes") {
                        self.error.clear();
                    }
                }
                "statistics_error" => { self.error=message; }
                "campaign_status" => { self.campaign_note = message; }
                "army_groups" => {
                    self.join_army_groups = event["enabled"].as_bool().unwrap_or(false);
                    self.notice = if self.join_army_groups { "Автовступление в группы армий включено" } else { "Автовступление в группы армий выключено" }.into();
                }
                "emergency" => {
                    self.emergency_enabled = event["enabled"].as_bool().unwrap_or(false);
                    self.emergency_has_key = event["has_key"].as_bool().unwrap_or(false);
                    self.emergency_key.clear();
                    self.notice = "Настройки DeepSeek сохранены".into();
                }
                "state" => {
                    self.busy = event["busy"].as_bool().unwrap_or(false);
                    self.status = message;
                }
                "progress" => {
                    if let Some(steps) = event["steps"].as_array() {
                        self.steps = steps
                            .iter()
                            .map(|s| {
                                (
                                    s["title"].as_str().unwrap_or("").to_owned(),
                                    s["status"].as_str().unwrap_or("waiting").to_owned(),
                                )
                            })
                            .collect();
                    }
                }
                "window" => {
                    self.hidden = event["hidden"].as_bool().unwrap_or(false);
                    self.notice = message;
                }
                "log" => {
                    self.logs.push_back(message);
                    if self.logs.len() > 1000 {
                        self.logs.pop_front();
                    }
                }
                "error" => {
                    self.error = message;
                    self.pending_start = None;
                }
                _ => (),
            }
        }
        if let Some(child) = self.child.as_mut() {
            if let Ok(Some(_)) = child.try_wait() {
                self.child = None;
                self.input = None;
                self.ready = false;
                self.busy = false;
                if !self.closing {
                    self.error =
                        "Рабочий процесс завершился. Закрой и снова открой помощника.".into();
                }
            }
        }
    }
    fn heading(ui: &mut egui::Ui, eyebrow: &str, title: &str, description: &str) {
        ui.label(RichText::new(eyebrow).size(12.).color(MINT));
        ui.label(RichText::new(title).size(32.).strong());
        ui.label(RichText::new(description).color(MUTED));
        ui.add_space(15.);
    }
    fn progress(&self, ui: &mut egui::Ui) {
        let waiting: Vec<(String, String)> = [
            "Помощь альянсу", "Воздушные поставки: вызов и сбор",
            "Награды радара", "Технологии: всё по порядку", "Пополнение войск",
            "Сборщики ресурсов", "Производственные очереди", "Пожертвования от 1/20", "Ежедневные действия и офицеры",
        ].iter().map(|title| (title.to_string(), "waiting".to_string())).collect();
        let steps = if self.steps.is_empty() { &waiting } else { &self.steps };
        let done = steps.iter().filter(|(_, state)| state == "done").count();
        card().inner_margin(14.).show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.spacing_mut().item_spacing.y = 5.;
            ui.horizontal(|ui| {
                ui.label(RichText::new("ПРОГРЕСС ОПЕРАЦИИ").size(13.).strong().color(MINT));
                if self.busy || (!self.ready && !self.animation_test) { ui.spinner(); }
            });
            ui.add(egui::ProgressBar::new(done as f32 / steps.len() as f32)
                .fill(MINT).desired_height(20.)
                .text(RichText::new(format!("Проверено {done} из {} этапов", steps.len())).color(Color32::WHITE)));
            if !self.ready || self.pending_start.is_some() || (self.busy && self.steps.is_empty()) {
                ui.label(RichText::new(&self.status).size(12.).color(MUTED));
            }
            ui.columns(2, |columns| {
                for column in columns.iter_mut() {
                    column.spacing_mut().interact_size.y = 18.;
                    column.spacing_mut().item_spacing.y = 4.;
                    column.visuals_mut().disabled_alpha = 1.;
                }
                for (index, (title, state)) in steps.iter().enumerate() {
                    let (label, color) = match state.as_str() {
                        "done" => ("Проверено", MINT),
                        "running" if self.busy => ("Сейчас", MINT),
                        "running" | "paused" => ("Прервано", Color32::LIGHT_YELLOW),
                        "deferred" => ("Повтор в следующем проходе", Color32::LIGHT_YELLOW),
                        _ => ("Ожидает", MUTED),
                    };
                    let transition = columns[index % 2].ctx().animate_bool_with_time(egui::Id::new(("stage-fade", index)), state == "done" || state == "running", 0.3);
                    let color = if state == "running" { Color32::from_rgb((151. - transition * 45.) as u8, (167. + transition * 57.) as u8, 183) } else { color };
                    let mut checked = state == "done";
                    columns[index % 2].add_enabled(false, egui::Checkbox::new(&mut checked,
                        RichText::new(format!("{:02}  {title} · {label}", index + 1)).size(12.).color(color)));
                }
            });
            ui.label(RichText::new("Галочка — проверка этапа завершена. Заполнение полосы основано на результатах бота.")
                .size(11.).color(MUTED));
        });
        ui.add_space(12.);
    }
    fn mascot(&self, ui: &mut egui::Ui, texture: &egui::TextureHandle, size: f32, uv: egui::Rect) {
        let time = ui.input(|i| i.time);
        let motion = ui.style().animation_time > 0.;
        let greeting = motion && time < self.greeting_until;
        let angle = if greeting { ((self.greeting_until - time) as f32 * 7.).sin() * 0.045 }
            else if motion { (time as f32 * 1.4).sin() * 0.012 } else { 0. };
        ui.add(egui::Image::new((texture.id(), Vec2::splat(size))).uv(uv).rotate(angle, egui::vec2(0.5, 1.)));
    }
    fn draw_character(&self, ui: &mut egui::Ui, size: f32, character: usize) {
        let time = ui.input(|i| i.time);
        let animated = ui.style().animation_time > 0.;
        let character = self.animation.character(character);
        if !(animated && time < self.greeting_until) {
            let cell = if animated { self.animation.cell(time) } else { 0 };
            let alternate = animated && character > 0 &&
                ((cell == 0 && time % 5.2 < 0.17) || (cell == 6 && time % 1.4 > 0.7));
            let atlas = if alternate { &self.alternate_poses[character - 1] } else { &self.poses[character] };
            if let Some(texture) = atlas {
                let left = (cell % 4) as f32 / 4.;
                let top = (cell / 4) as f32 / 2.;
                self.mascot(ui, texture, size, egui::Rect::from_min_max(egui::pos2(left, top), egui::pos2(left + 0.25, top + 0.5)));
                return;
            }
        }
        let crew = if animated && time < self.greeting_until { &self.crew_salute }
            else if animated && time % 5.2 < 0.17 { &self.crew_blink } else { &self.crew };
        let (texture, left, right) = match character {
            1 => (crew, 0., 0.5),
            2 => (crew, 0.5, 1.),
            _ => (if animated && time < self.greeting_until { &self.operator_salute } else { &self.operator }, 0., 1.),
        };
        if let Some(texture) = texture {
            self.mascot(ui, texture, size, egui::Rect::from_min_max(egui::pos2(left, 0.), egui::pos2(right, 1.)));
        }
    }
    fn home(&mut self, ui: &mut egui::Ui) {
        mint_card(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.horizontal(|ui| {
                ui.allocate_ui_with_layout(Vec2::new((ui.available_width() - 220.).max(250.), 200.),
                    egui::Layout::top_down(egui::Align::Center), |ui| {
                    ui.label(RichText::new("КОМАНДНЫЙ ПУНКТ").size(25.).strong());
                    ui.label(RichText::new(["Связист", "Механик", "Морской офицер"][self.animation.character(self.character)]).color(MINT));
                    ui.label(RichText::new(self.animation.motion.label()).size(12.).color(MUTED));
                    ui.add_space(15.);
                    if ui.add_sized([250., 58.], egui::Button::new(RichText::new("Сменить персонажа").size(18.).strong()).fill(Color32::from_rgb(34, 87, 69))).clicked() {
                        self.character = (self.character + 1) % 3;
                        if let Err(error) = std::fs::write(self.root.join("character.txt"), self.character.to_string()) {
                            self.error = format!("Не удалось сохранить персонажа: {error}");
                        }
                        self.greeting_until = ui.input(|i| i.time) + 2.4;
                    }
                    ui.label(RichText::new("Связист  /  Механик  /  Морской офицер").size(11.).color(MUTED));
                });
                self.draw_character(ui, 200., self.character);
            });
        });
        ui.add_space(12.);

        Self::heading(
            ui,
            "ЦЕНТР УПРАВЛЕНИЯ",
            "Управление операцией",
            "Настрой схемы один раз. Запускай обычные действия одной кнопкой.",
        );
        card()
            .fill(Color32::from_rgb(23, 49, 44))
            .inner_margin(24.)
            .show(ui, |ui| {
                ui.set_width(ui.available_width());
                ui.label(
                    RichText::new(if self.busy {
                        "В РАБОТЕ"
                    } else {
                        "СОСТОЯНИЕ"
                    })
                    .size(12.)
                    .color(MINT),
                );
                ui.label(RichText::new(&self.status).size(23.).strong());
                ui.add_space(10.);
                ui.horizontal_wrapped(|ui| {
                    if ui
                        .add_enabled(
                            self.ready && !self.busy && self.pending_start.is_none(),
                            egui::Button::new(
                                RichText::new("Запустить автоферму")
                                    .color(Color32::from_rgb(9, 32, 27))
                                    .strong(),
                            )
                            .fill(MINT)
                            .min_size(Vec2::new(250., 52.)),
                        )
                        .clicked()
                    {
                        self.start("cycle");
                    }
                    if ui
                        .add_enabled(
                            self.busy,
                            egui::Button::new("Стоп").min_size(Vec2::new(105., 52.)),
                        )
                        .clicked()
                    {
                        self.send(json!({"command":"stop"}));
                        self.status = "Останавливается…".into();
                    }
                });
                ui.add_enabled_ui(!self.busy, |ui| {
                    ui.checkbox(&mut self.repeat, "Повторять каждые 5 минут");
                });
                let mut join_groups = self.join_army_groups;
                if ui.add_enabled(self.ready, egui::Checkbox::new(&mut join_groups,
                    "Автовступление в группы армий альянса")).changed() {
                    self.send(json!({"command":"army_groups", "enabled":join_groups}));
                }
                ui.label(RichText::new("При свободном месте · проверка после пополнения войск").size(12.).color(MUTED));
            });
        ui.add_space(12.);
        ui.label(
            RichText::new("ОДИН ЗАПУСК · ШЕСТЬ НАПРАВЛЕНИЙ")
                .size(12.)
                .color(MUTED),
        );
        for row in [
            [
                ("01 / АЛЬЯНС", "Помощь всем", "Пожертвования от 1/20"),
                (
                    "02 / ПОСТАВКИ",
                    "Вызвать и собрать",
                    "Обычные воздушные ящики",
                ),
            ],
            [
                ("03 / МИССИИ", "Радар и офицеры", "Награды и быстрый выбор"),
                (
                    "04 / ЕЖЕДНЕВНОЕ",
                    "Действия и награды",
                    "Часть заданий поддерживается",
                ),
            ],
            [
                (
                    "05 / РЕСУРСЫ",
                    "Добыча и завод",
                    "Твои схемы отрядов и очередей",
                ),
                (
                    "06 / РАЗВИТИЕ",
                    "Технологии по порядку",
                    "При свободной очереди",
                ),
            ],
        ] {
            ui.columns(2, |cols| {
                for (col, (tag, title, detail)) in cols.iter_mut().zip(row) {
                    card().inner_margin(14.).show(col, |ui| {
                        ui.set_width(ui.available_width());
                        ui.spacing_mut().item_spacing.y = 5.;
                        ui.label(RichText::new(tag).size(11.).color(MINT));
                        ui.label(RichText::new(title).size(18.).strong());
                        ui.label(RichText::new(detail).size(13.).color(MUTED));
                    });
                }
            });
        }
        ui.add_space(8.);
        mint_card(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.horizontal(|ui| {
                ui.allocate_ui_with_layout(Vec2::new((ui.available_width() - 220.).max(250.), 220.),
                    egui::Layout::top_down(egui::Align::Center), |ui| {
                    ui.label(RichText::new("КАМПАНИЯ").size(25.).strong());
                    ui.label(RichText::new(if self.campaign_sea { "Морской офицер" } else { "Механик" }).color(MINT));
                    ui.horizontal(|ui| {
                        let space = ((ui.available_width() - 270.) / 2.).max(0.);
                        ui.add_space(space);
                        let changed = ui.selectable_value(&mut self.campaign_sea, false, "Наземная").changed()
                            | ui.selectable_value(&mut self.campaign_sea, true, "Морская").changed();
                        if changed { self.greeting_until = ui.input(|i| i.time) + 2.4; }
                    });
                    ui.add_space(10.);
                    if ui.add_enabled(self.ready && !self.busy,
                        egui::Button::new(RichText::new("Запустить кампанию").size(18.).strong().color(Color32::from_rgb(9, 32, 27)))
                            .fill(MINT).min_size(Vec2::new(250., 58.))).clicked() {
                        self.start(if self.campaign_sea { "campaign_sea" } else { "campaign" });
                    }
                    if !self.campaign_note.is_empty() {
                        ui.label(RichText::new(format!("Последний результат: {}", self.campaign_note)).size(12.).color(Color32::LIGHT_YELLOW));
                    }
                });
                self.draw_character(ui, 200., if self.campaign_sea { 2 } else { 1 });
            });
            ui.label(RichText::new("До трёх боёв за запуск. Пополнение собирается в обычном цикле.").size(13.).color(MUTED));
            ui.label(RichText::new("Быстрое пополнение: бесплатно и за золото до дневного лимита").size(13.).color(MINT));
            ui.label(RichText::new("Поддерживается уничтожение сил «Ворона». При неизвестной цели выполняется восстановление.").size(12.).color(MUTED));
        });
        ui.add_space(12.);
        ui.label(RichText::new("ПОСЛЕДНЕЕ СОБЫТИЕ").size(12.).color(MUTED));
        ui.label(
            self.logs
                .back()
                .map(String::as_str)
                .unwrap_or("Здесь появятся действия и результаты проверки."),
        );
    }
    fn collectors(&mut self, ui: &mut egui::Ui) {
        Self::heading(
            ui,
            "СХЕМА ДОБЫЧИ",
            "Пять отрядов — твой план",
            "Сначала максимальный доступный уровень. Занятые отряды заканчивают добычу.",
        );
        if self.busy {
            ui.label(RichText::new("Схемы доступны после остановки автофермы.").color(MINT));
        }
        ui.add_enabled_ui(self.ready && !self.busy, |ui| {
            ui.horizontal_wrapped(|ui| {
                for (name, indexes) in [
                    ("2 фермы · 2 нефти · 1 шахта", [0, 0, 1, 1, 2]),
                    ("1 ферма · 2 нефти · 2 шахты", [0, 1, 1, 2, 2]),
                    ("2 фермы · 1 нефть · 2 шахты", [0, 0, 1, 2, 2]),
                ] {
                    if ui.button(name).clicked() {
                        self.plan = indexes.iter().map(|i| RESOURCES[*i].into()).collect();
                        self.dirty = true;
                    }
                }
            });
            ui.add_space(12.);
            for (i, value) in self.plan.iter_mut().enumerate() {
                ui.horizontal(|ui| {
                    ui.label(RichText::new(format!("ОТРЯД  {:02}", i + 1)).color(MUTED));
                    egui::ComboBox::from_id_salt(("collector", i))
                        .width(220.)
                        .selected_text(value.as_str())
                        .show_ui(ui, |ui| {
                            for name in RESOURCES {
                                self.dirty |=
                                    ui.selectable_value(value, name.to_string(), name).changed();
                            }
                        });
                });
            }
            ui.add_space(14.);
            if ui.button("Сохранить схемы").clicked() {
                self.save();
            }
        });
        ui.add_space(20.);
        ui.label(RichText::new("Ферма — финансирование · Нефть — нефтяная вышка · Шахта — сталь.\nИзменения применяются при следующем запуске. Платный шестой сборщик не используется.").color(MUTED));
    }
    fn factory(&mut self, ui: &mut egui::Ui) {
        self.draw_character(ui, 100., 1);
        Self::heading(
            ui,
            "АГРЕГАТНЫЙ ЗАВОД",
            "Производство по порядку",
            "Для каждой мастерской задай материал и количество. Порядок идёт сверху вниз.",
        );
        if self.production.is_null() {
            return;
        }
        if self.busy {
            ui.label(RichText::new("Схемы доступны после остановки автофермы.").color(MINT));
        }
        ui.add_enabled_ui(self.ready && !self.busy, |ui| {
            let mut enabled = self.production["enabled"].as_bool().unwrap_or(false);
            if ui.checkbox(&mut enabled, "Включить в автоферму").changed() {
                self.production["enabled"] = json!(enabled);
                self.dirty = true;
            }
            let mut repeat = self.production["repeat"].as_bool().unwrap_or(false);
            let mut limit = self.production["limit"].as_u64().unwrap_or(33) as u32;
            ui.horizontal_wrapped(|ui| {
                if ui.checkbox(&mut repeat, "Повторять схему").changed() {
                    self.production["repeat"] = json!(repeat);
                    self.dirty = true;
                }
                ui.label("Заполнять до");
                if ui
                    .add(egui::DragValue::new(&mut limit).range(1..=33))
                    .changed()
                {
                    self.production["limit"] = json!(limit);
                    self.dirty = true;
                }
                ui.label("мест в очереди");
            });
            for (workshop, recipe) in self.production["workshops"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .enumerate()
            {
                let steps = recipe.as_array_mut().unwrap();
                card().inner_margin(16.).show(ui, |ui| {
                    ui.label(
                        RichText::new(format!("Мастерская {}", workshop + 1))
                            .size(19.)
                            .strong(),
                    );
                    let mut movement = None;
                    let mut deletion = None;
                    let len = steps.len();
                    for (index, step) in steps.iter_mut().enumerate() {
                        let mut material = step["material"].as_str().unwrap_or("Доска").to_owned();
                        let mut count = step["count"].as_u64().unwrap_or(1) as u32;
                        ui.horizontal_wrapped(|ui| {
                            ui.label(format!("{:02}", index + 1));
                            egui::ComboBox::from_id_salt((workshop, index))
                                .width(175.)
                                .selected_text(&material)
                                .show_ui(ui, |ui| {
                                    for name in MATERIALS {
                                        if ui
                                            .selectable_value(&mut material, name.into(), name)
                                            .changed()
                                        {
                                            step["material"] = json!(material);
                                            self.dirty = true;
                                        }
                                    }
                                });
                            if ui
                                .add(
                                    egui::DragValue::new(&mut count)
                                        .range(1..=999)
                                        .suffix(" шт."),
                                )
                                .changed()
                            {
                                step["count"] = json!(count);
                                self.dirty = true;
                            }
                            if ui
                                .add_enabled(index > 0, egui::Button::new("Выше"))
                                .clicked()
                            {
                                movement = Some((index, index - 1));
                            }
                            if ui
                                .add_enabled(index + 1 < len, egui::Button::new("Ниже"))
                                .clicked()
                            {
                                movement = Some((index, index + 1));
                            }
                            if ui.button("Убрать").clicked() {
                                deletion = Some(index);
                            }
                        });
                    }
                    if let Some((a, b)) = movement {
                        steps.swap(a, b);
                        self.dirty = true;
                    }
                    if let Some(index) = deletion {
                        steps.remove(index);
                        self.dirty = true;
                    }
                    if steps.is_empty() {
                        ui.label(
                            RichText::new("Мастерская пропускается — добавь первый шаг.")
                                .color(MUTED),
                        );
                    }
                    if ui
                        .add_enabled(steps.len() < 20, egui::Button::new("+ Добавить шаг"))
                        .clicked()
                    {
                        steps.push(json!({"material":"Доска","count":1}));
                        self.dirty = true;
                    }
                });
            }
            if ui.button("Сохранить схемы").clicked() {
                self.save();
            }
        });
        ui.label(RichText::new("Уже запущенное производство продолжится. Новая схема применяется к свободным местам.").color(MUTED));
    }
    fn journal(&mut self, ui: &mut egui::Ui) {
        Self::heading(
            ui,
            "ЖУРНАЛ",
            "Действия и результаты",
            "События текущего сеанса. Полная история сохраняется в bot.log.",
        );
        for line in &self.logs {
            ui.label(line);
        }
        if self.logs.is_empty() {
            ui.label("Пока нет событий. Запусти автоферму или проверку подключения.");
        }
    }
    fn guide(&mut self, ui: &mut egui::Ui) {
        Self::heading(
            ui,
            "НАСТРОЙКА",
            "Всё под рукой",
            "Игра работает через LDPlayer, управление идёт внутри эмулятора.",
        );
        card().show(ui, |ui| {
            ui.label(RichText::new("DeepSeek · только при сбое или угрозе").size(19.).strong());
            ui.label("Без внутреннего почасового лимита. Передаётся текст игрового экрана выше чата и причина сбоя. Вызовы оплачиваются по твоему тарифу DeepSeek.");
            ui.label("Возврат из известных меню проверяет сам бот. Автотелепорт пока не настроен: при угрозе — пауза.");
            ui.add_enabled_ui(!self.busy, |ui| {
                ui.label("Место спасения · координаты в текущем городе");
                ui.horizontal(|ui| {
                    ui.label("X"); ui.add(egui::DragValue::new(&mut self.rescue_x).range(0..=999999));
                    ui.label("Y"); ui.add(egui::DragValue::new(&mut self.rescue_y).range(0..=999999));
                });
                ui.checkbox(&mut self.rescue_destination, "Использовать мои координаты для спасения");
                ui.checkbox(&mut self.emergency_enabled, "Включить аварийную помощь DeepSeek");
                ui.label(if self.emergency_has_key {"Ключ сохранён и защищён Windows. Пустое поле сохраняет прежний ключ."} else {"Вставь ключ API DeepSeek. Он не попадёт в журнал."});
                ui.add(egui::TextEdit::singleline(&mut self.emergency_key).password(true).hint_text("Ключ API DeepSeek"));
                if ui.button("Сохранить DeepSeek").clicked() {
                    let key = self.emergency_key.clone();
                    self.send(json!({"command":"emergency_save", "enabled":self.emergency_enabled, "key":key,
                        "x":self.rescue_x,"y":self.rescue_y,"destination_set":self.rescue_destination}));
                }
            });
        });
        for (title, body) in [
            (
                "Перед запуском",
                "Открой карту или базу. Русский язык, разрешение Android 1920 × 1080. В LDPlayer включи локальное подключение ADB.",
            ),
            (
                "Другие приложения",
                "Можно работать за компьютером: помощник не двигает мышь Windows. В самой игре во время цикла не нажимай — изменение экрана может вызвать паузу.",
            ),
            (
                "Остановка",
                "Стоп или Escape отменяет новые действия. При закрытии помощник дожидается остановки и возвращает скрытое им окно LDPlayer.",
            ),
            (
                "Проверка человека",
                "При неизвестном экране или пазле бот ставится на паузу. Автоматическая проверка пазла пока отложена.",
            ),
            (
                "Расходы",
                "Обычные ресурсы и ограниченные предметы ежедневных заданий. Платные ускорения и шестой сборщик не используются. Улучшение командного пункта исключено.",
            ),
        ] {
            ui.label(RichText::new(title).size(19.).strong());
            ui.label(RichText::new(body).color(MUTED));
            ui.add_space(8.);
        }
        if ui
            .add_enabled(
                self.ready && !self.busy,
                egui::Button::new("Проверить подключение без нажатий"),
            )
            .clicked()
        {
            self.start("inspect");
        }
        ui.label(
            RichText::new(format!("Файлы помощника: {}", self.root.display()))
                .size(12.)
                .color(MUTED),
        );
    }
}
impl eframe::App for Helper {
    fn clear_color(&self, _visuals: &egui::Visuals) -> [f32; 4] { [0., 0., 0., 0.] }
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        let now = ctx.input(|i| i.time);
        self.poll(now);
        self.animation.tick(now);
        if ctx.input(|i| i.key_pressed(egui::Key::Escape)) && self.busy {
            self.send(json!({"command":"stop"}));
        }
        if ctx.input(|i| i.viewport().close_requested()) && self.child.is_some() {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
            if !self.closing {
                self.closing = true;
                self.status = "Остановка перед закрытием…".into();
                self.send(json!({"command":"shutdown"}));
            }
        }
        if self.closing && self.child.is_none() {
            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
        }
        if self.greeting_until < 0. { self.greeting_until = ctx.input(|i| i.time) + 2.4; }
        egui::TopBottomPanel::top("mint-titlebar").frame(egui::Frame::new().fill(Color32::from_rgb(24, 64, 53)).corner_radius(egui::CornerRadius { nw: 14, ne: 14, sw: 0, se: 0 }).inner_margin(8.)).show(ctx, |ui| {
            ui.horizontal(|ui| {
                let drag = ui.add(egui::Label::new(RichText::new("WARPATH  /  ТАКТИЧЕСКИЙ ПОМОЩНИК").color(MINT).strong()).sense(egui::Sense::drag()));
                if drag.drag_started() { ctx.send_viewport_cmd(egui::ViewportCommand::StartDrag); }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button("Закрыть").clicked() { ctx.send_viewport_cmd(egui::ViewportCommand::Close); }
                    if ui.button("Развернуть").clicked() { let maximized = ctx.input(|i| i.viewport().maximized.unwrap_or(false)); ctx.send_viewport_cmd(egui::ViewportCommand::Maximized(!maximized)); }
                    if ui.button("Свернуть").clicked() { ctx.send_viewport_cmd(egui::ViewportCommand::Minimized(true)); }
                });
            });
        });
        if self.animation_test {
            egui::TopBottomPanel::top("animation-check").show(ctx, |ui| {
                ui.label("ПРОВЕРКА АНИМАЦИЙ · ИГРА НЕ ИЗМЕНЯЕТСЯ");
                ui.horizontal_wrapped(|ui| {
                    for motion in [Motion::Idle, Motion::Stage, Motion::Success, Motion::Recovery,
                        Motion::Production, Motion::SeaCampaign, Motion::Stopped] {
                        if ui.button(motion.label()).clicked() {
                            self.animation.receive(motion, now);
                            self.greeting_until = 0.;
                        }
                    }
                });
            });
        }
        egui::SidePanel::left("navigation")
            .exact_width(225.)
            .resizable(false)
            .frame(
                egui::Frame::new()
                    .fill(Color32::from_rgb(11, 19, 28))
                    .corner_radius(egui::CornerRadius { nw: 0, ne: 0, sw: 14, se: 0 })
                    .inner_margin(18.),
            )
            .show(ctx, |ui| {
                ui.add_space(20.);
                ui.label(RichText::new("WARPATH").size(27.).strong().color(MINT));
                ui.label(RichText::new("ТАКТИЧЕСКАЯ СИСТЕМА").size(11.).color(MUTED));
                ui.add_space(12.);
                self.draw_character(ui, 125., self.character);
                ui.label(RichText::new(["ПОЗЫВНОЙ / СВЯЗИСТ", "ПОЗЫВНОЙ / МЕХАНИК", "ПОЗЫВНОЙ / ОФИЦЕР"][self.animation.character(self.character)]).size(10.).color(MINT));
                ui.add_space(16.);
                for (index, name) in ["Обзор", "Сборщики", "Производство", "Журнал", "Настройка", "Статистика"]
                    .iter()
                    .enumerate()
                {
                    if ui
                        .add_sized(
                            [185., 44.],
                            egui::Button::selectable(
                                self.page == index,
                                format!("{:02}    {}", index + 1, name),
                            ),
                        )
                        .clicked()
                    {
                        self.page = index;
                    }
                }
                ui.add_space(35.);
                ui.separator();
                ui.add_space(10.);
                ui.label(RichText::new("ОКНО ЭМУЛЯТОРА").size(11.).color(MUTED));
                if ui
                    .add_enabled(
                        self.ready,
                        egui::Button::new(if self.hidden {
                            "Показать LDPlayer"
                        } else {
                            "Скрыть LDPlayer"
                        }),
                    )
                    .clicked()
                {
                    self.send(json!({"command":if self.hidden{"show"}else{"hide"}}));
                }
                ui.label(
                    RichText::new(if self.hidden {
                        "Скрыт · игра работает"
                    } else {
                        "Окно доступно"
                    })
                    .size(12.)
                    .color(MUTED),
                );
                if self.busy && ui.button("Остановить автоферму").clicked() {
                    self.send(json!({"command":"stop"}));
                    self.status = "Останавливается…".into();
                }
                if self.dirty {
                    ui.add_space(15.);
                    ui.label(
                        RichText::new("Есть несохранённые изменения")
                            .size(12.)
                            .color(Color32::LIGHT_YELLOW),
                    );
                }
            });
        egui::CentralPanel::default()
            .frame(
                egui::Frame::new()
                    .fill(Color32::from_rgb(14, 23, 33))
                    .corner_radius(egui::CornerRadius { nw: 0, ne: 0, sw: 0, se: 14 })
                    .inner_margin(26.),
            )
            .show(ctx, |ui| {
                if self.page == 5 {
                    ui.horizontal(|ui| {
                        ui.colored_label(MINT, if self.busy {"● В РАБОТЕ"} else {"○ ОЖИДАНИЕ"});
                        ui.label(RichText::new(&self.status).size(12.).color(MUTED));
                    });
                    ui.add_space(8.);
                } else { self.progress(ui); }
                if !self.error.is_empty() {
                    ui.colored_label(Color32::LIGHT_RED, &self.error);
                }
                if !self.notice.is_empty() {
                    ui.label(RichText::new(&self.notice).color(MINT));
                }
                ui.add_enabled_ui(!self.closing, |ui| {
                    egui::ScrollArea::vertical()
                        .id_salt(self.page)
                        .stick_to_bottom(self.page == 3)
                        .show(ui, |ui| {
                            let fade = ui.ctx().animate_value_with_time(egui::Id::new("page-transition"), self.page as f32, 0.22);
                            ui.add_space(((fade - self.page as f32).abs() * 5.).min(12.));
                            match self.page {
                            0 => self.home(ui),
                            1 => self.collectors(ui),
                            2 => self.factory(ui),
                            3 => self.journal(ui),
                            5 => {
                                if ui.button("Обновить показатели").clicked() { self.send(json!({"command":"statistics"})); }
                                statistics::show(ui,&self.statistics);
                            },
                            _ => self.guide(ui),
                            }
                        });
                });
            });
        ctx.request_repaint_after(Duration::from_millis(150));
    }
}
impl Drop for Helper {
    fn drop(&mut self) {
        if let Some(mut input) = self.input.take() {
            let _ = writeln!(input, "{{\"command\":\"shutdown\"}}");
        }
    }
}
fn main() -> eframe::Result {
    let mut viewport = egui::ViewportBuilder::default()
        .with_title(if std::env::args().any(|arg| arg == "--animation-check") { "Warpath — проверка анимаций" } else { "Warpath — помощник" })
        .with_decorations(false)
        .with_transparent(true)
        .with_inner_size([1140., 820.])
        .with_min_inner_size([960., 650.]);
    if let Ok(icon) =
        eframe::icon_data::from_png_bytes(include_bytes!("../../assets/app-icon-64.png"))
    {
        viewport = viewport.with_icon(icon);
    }
    eframe::run_native(
        "Warpath — помощник",
        eframe::NativeOptions {
            viewport,
            ..Default::default()
        },
        Box::new(|cc| Ok(Box::new(Helper::new(cc)))),
    )
}

