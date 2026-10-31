#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Motion {
    #[default]
    Idle,
    Stage,
    Success,
    Recovery,
    Production,
    SeaCampaign,
    Stopped,
}

impl Motion {
    pub fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "idle" => Self::Idle,
            "stage" => Self::Stage,
            "success" => Self::Success,
            "recovery" => Self::Recovery,
            "production" => Self::Production,
            "sea_campaign" => Self::SeaCampaign,
            "stopped" => Self::Stopped,
            _ => return None,
        })
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Idle => "Ожидание",
            Self::Stage => "Проверяю этап",
            Self::Success => "Действие завершено",
            Self::Recovery => "Восстанавливаю работу",
            Self::Production => "Работаю с производством",
            Self::SeaCampaign => "Запускаю морскую кампанию",
            Self::Stopped => "Ферма остановлена",
        }
    }
}

#[derive(Default)]
pub struct Animation {
    pub motion: Motion,
    pub since: f64,
    pending: Option<Motion>,
}

impl Animation {
    pub fn receive(&mut self, motion: Motion, now: f64) {
        // Let a real success gesture finish, but never delay recovery or Stop.
        if self.motion == Motion::Success && now - self.since < 1.2
            && !matches!(motion, Motion::Recovery | Motion::Stopped)
        {
            self.pending = Some(motion);
            return;
        }
        self.motion = motion;
        self.since = now;
        self.pending = None;
    }

    pub fn tick(&mut self, now: f64) {
        if self.motion == Motion::Success && now - self.since >= 1.2 {
            self.motion = self.pending.take().unwrap_or(Motion::Idle);
            self.since = now;
        }
    }

    pub fn cell(&self, now: f64) -> usize {
        let elapsed = (now - self.since).max(0.);
        match self.motion {
            Motion::Stage => if elapsed % 3.2 < 0.7 { 1 } else { 2 },
            Motion::Success => 3,
            Motion::Recovery => 4,
            Motion::Idle => if elapsed % 7.0 > 5.8 { 5 } else { 0 },
            Motion::Production | Motion::SeaCampaign => 6,
            Motion::Stopped => 7,
        }
    }

    pub fn character(&self, selected: usize) -> usize {
        match self.motion {
            Motion::Production => 1,
            Motion::SeaCampaign => 2,
            _ => selected,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn success_is_visible_before_next_stage_and_stop_cancels_pending() {
        let mut animation = Animation::default();
        animation.receive(Motion::Success, 1.);
        animation.receive(Motion::Production, 1.01);
        assert_eq!(animation.motion, Motion::Success);
        animation.tick(2.3);
        assert_eq!(animation.motion, Motion::Production);
        animation.receive(Motion::Success, 3.);
        animation.receive(Motion::Stage, 3.01);
        animation.receive(Motion::Stopped, 3.02);
        animation.tick(10.);
        assert_eq!(animation.motion, Motion::Stopped);
        assert_eq!(animation.cell(10.), 7);
    }

    #[test]
    fn recovery_preempts_success_and_role_changes_are_temporary() {
        let mut animation = Animation::default();
        animation.receive(Motion::Success, 1.);
        animation.receive(Motion::Recovery, 1.01);
        assert_eq!(animation.cell(1.02), 4);
        animation.receive(Motion::Production, 2.);
        assert_eq!(animation.character(0), 1);
        animation.receive(Motion::SeaCampaign, 3.);
        assert_eq!(animation.character(0), 2);
        animation.receive(Motion::Idle, 4.);
        assert_eq!(animation.character(0), 0);
        assert_eq!(Motion::parse("not-an-event"), None);
    }
}
