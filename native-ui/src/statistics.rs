use eframe::egui::{self, Color32, RichText, Vec2};
use serde_json::Value;
use crate::{MINT, MUTED, card, mint_card};

const COLORS: [Color32; 6] = [MINT, Color32::from_rgb(111,183,247),
    Color32::from_rgb(246,196,110), Color32::from_rgb(179,151,235),
    Color32::from_rgb(238,147,154), Color32::from_rgb(116,207,217)];

fn rows(data: &Value, key: &str) -> Vec<(String, u64)> {
    data[key].as_object().map(|o| o.iter().map(|(k,v)|(k.clone(),v.as_u64().unwrap_or(0))).collect()).unwrap_or_default()
}
fn total(data: &Value, key: &str) -> u64 { rows(data,key).iter().map(|r|r.1).sum() }
fn amount(n: u64) -> String {
    if n>=1_000_000 { format!("{:.2} млн",n as f64/1_000_000.) }
    else if n>=10_000 { format!("{:.1} тыс.",n as f64/1000.) } else { n.to_string() }
}

fn donut(ui: &mut egui::Ui, title: &str, values: &[(String,u64)], unit: &str) {
    card().show(ui,|ui| {
        ui.label(RichText::new(title).size(19.).strong());
        let sum: u64=values.iter().map(|r|r.1).sum();
        let (rect,_) = ui.allocate_exact_size(Vec2::new(ui.available_width(),200.),egui::Sense::hover());
        let center=rect.center(); let radius=77.; let painter=ui.painter();
        painter.circle_stroke(center,radius,egui::Stroke::new(17_f32,Color32::from_rgb(35,54,59)));
        let mut start=-std::f32::consts::FRAC_PI_2;
        if sum>0 {
            for (i,(_,value)) in values.iter().enumerate() {
                let sweep=*value as f32/sum as f32*std::f32::consts::TAU;
                let points=(0..=80).map(|j|center+Vec2::angled(start+sweep*j as f32/80.)*radius).collect();
                painter.add(egui::Shape::line(points,egui::Stroke::new(17_f32,COLORS[i%6])));
                start+=sweep;
            }
        }
        painter.text(center-Vec2::new(0.,9.),egui::Align2::CENTER_CENTER,amount(sum),egui::FontId::proportional(28.),Color32::WHITE);
        painter.text(center+Vec2::new(0.,20.),egui::Align2::CENTER_CENTER,unit,egui::FontId::proportional(12.),MUTED);
        if values.is_empty() { ui.label(RichText::new("Первые результаты появятся после работы бота").size(12.).color(MUTED)); }
        for (i,(name,value)) in values.iter().enumerate() {
            ui.horizontal(|ui| {
                ui.colored_label(COLORS[i%6],"●"); ui.label(name);
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center),|ui| {
                    ui.strong(amount(*value));
                    ui.label(RichText::new(format!("{:.0}%",if sum>0 {*value as f64/sum as f64*100.} else {0.})).size(12.).color(MUTED));
                });
            });
        }
    });
}

pub fn show(ui: &mut egui::Ui, data: &Value) {
    mint_card(ui,|ui| {
        ui.label(RichText::new("WARPATH / ОПЕРАТИВНАЯ АНАЛИТИКА").size(11.).color(MINT));
        ui.label(RichText::new("Результаты операций").size(32.).strong());
        ui.label(RichText::new("Подтверждённые действия. Сохранение между запусками.").color(MUTED));
        ui.add_space(12.);
        ui.columns(3,|cols| {
            for (i,(key,label)) in [("dispatches","ОТПРАВЛЕНО ОТРЯДОВ"),("queued","ДОБАВЛЕНО В ОЧЕРЕДЬ"),("produced","ПРОИЗВЕДЕНО И ПОЛУЧЕНО")].iter().enumerate() {
                cols[i].label(RichText::new(*label).size(10.).color(MINT));
                cols[i].label(RichText::new(amount(total(data,key))).size(34.).strong());
            }
        });
    });
    ui.add_space(8.);
    ui.label(RichText::new(format!("Учёт с {}",data["since"].as_str().unwrap_or("первого запуска").replace('T'," · "))).size(12.).color(MUTED));
    ui.columns(2,|cols| {
        donut(&mut cols[0],"Распределение сборщиков",&rows(data,"dispatches"),"отправок");
        donut(&mut cols[1],"Выпуск материалов",&rows(data,"produced"),"получено");
    });
    ui.add_space(8.);
    card().show(ui,|ui| {
        ui.set_min_width(ui.available_width());
        ui.label(RichText::new("Месторождения / уровни").size(20.).strong());
        let mut levels=rows(data,"levels"); levels.sort_by_key(|r|r.0.parse::<u32>().unwrap_or(0));
        let max=levels.iter().map(|r|r.1).max().unwrap_or(1).max(1);
        if levels.is_empty() { ui.label("Пока нет подтверждённых отправок"); }
        for (level,count) in levels {
            ui.horizontal(|ui| {
                ui.add_sized([95.,28.],egui::Label::new(format!("Уровень {level}")));
                ui.add(egui::ProgressBar::new(count as f32/max as f32).desired_width((ui.available_width()-50.).max(50.)).fill(MINT).text(format!("{count} отправок")));
            });
        }
    });
    ui.add_space(8.);
    ui.columns(2,|cols| {
        donut(&mut cols[0],"Добыто сборщиками",&rows(data,"gathered"),"единиц");
        card().show(&mut cols[1],|ui| {
            ui.label(RichText::new("Ресурсы и производство").size(19.).strong());
            ui.label(RichText::new("Последний прочитанный запас").color(MUTED));
            for name in ["Финансирование","Сталь","Топливо"] {
                ui.horizontal(|ui| { ui.label(name); ui.strong(data["balances"][name].as_u64().map(amount).unwrap_or("Нет данных".into())); });
            }
            ui.separator();
            ui.label(RichText::new("Наблюдаемый приток в запас").color(MUTED));
            for (name,count) in rows(data,"inflow") { ui.label(format!("{name}: +{}",amount(count))); }
            ui.separator();
            for (name,count) in rows(data,"queued") { ui.label(format!("{name}: {count} в очередь")); }
            ui.separator();
            ui.label(RichText::new("Приток — положительные изменения запаса, включая награды. Это не точный объём добычи: расходы и округление игры влияют на итог.").size(12.).color(MUTED));
            ui.label(RichText::new("Добыча — прочитанный прогресс отрядов, отправленных после начала учёта; груз может ещё находиться в пути. Непрочитанные промежутки не оцениваются.").size(12.).color(MUTED));
            ui.label(RichText::new("Выпуск учитывается после получения полностью готовой очереди мастерской. Учитываются только материалы, добавленные ботом с начала учёта. Старые и неоднозначные результаты не добавляются.").size(12.).color(MUTED));
        });
    });
    ui.add_space(8.);
    card().show(ui,|ui| {
        ui.set_min_width(ui.available_width());
        ui.label(RichText::new("Активность по дням").size(20.).strong());
        let days=data["days"].as_object();
        if let Some(days)=days {
            let maximum=days.values().map(|d|d["queued"].as_u64().unwrap_or(0)).max().unwrap_or(1).max(1);
            for (day,values) in days.iter().rev().take(7) {
                ui.label(format!("{}    •    {} отправок    •    {} в очередь    •    {} получено",day,values["dispatches"].as_u64().unwrap_or(0),values["queued"].as_u64().unwrap_or(0),values["produced"].as_u64().unwrap_or(0)));
                ui.add(egui::ProgressBar::new(values["queued"].as_u64().unwrap_or(0) as f32/maximum as f32).desired_width(ui.available_width()).fill(COLORS[1]).text("Загрузка производства"));
            }
            if days.is_empty() { ui.label("История появится после первого подтверждённого действия"); }
        }
    });
}
