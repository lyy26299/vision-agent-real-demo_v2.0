use std::ffi::c_void;
use std::slice;

use webrtc_audio_processing::{
    config::EchoCanceller,
    Config,
    Processor,
};

struct Bridge {
    processor: Processor,
    frame_samples: usize,
    delay_ms: Option<u16>,
}

impl Bridge {
    fn new(sample_rate: u32) -> Result<Self, ()> {
        if sample_rate == 0 || sample_rate % 100 != 0 {
            return Err(());
        }

        let processor = Processor::new(sample_rate).map_err(|_| ())?;
        let mut bridge = Self {
            frame_samples: processor.num_samples_per_frame(),
            processor,
            delay_ms: None,
        };
        bridge.apply_config(None);
        Ok(bridge)
    }

    fn apply_config(&mut self, delay_ms: Option<u16>) {
        self.processor.set_config(Config {
            echo_canceller: Some(EchoCanceller::Full { stream_delay_ms: delay_ms }),
            high_pass_filter: Some(Default::default()),
            ..Default::default()
        });
        self.delay_ms = delay_ms;
    }

    fn maybe_update_delay(&mut self, delay_ms: i32) {
        let next = if delay_ms < 0 {
            None
        } else {
            Some(delay_ms.clamp(0, u16::MAX as i32) as u16)
        };

        let changed = match (self.delay_ms, next) {
            (None, None) => false,
            (Some(a), Some(b)) => a.abs_diff(b) >= 5,
            _ => true,
        };

        if changed {
            self.apply_config(next);
        }
    }
}

fn with_bridge_mut<T>(
    handle: *mut c_void,
    f: impl FnOnce(&mut Bridge) -> T,
) -> Option<T> {
    if handle.is_null() {
        return None;
    }
    let bridge = unsafe { &mut *(handle as *mut Bridge) };
    Some(f(bridge))
}

#[no_mangle]
pub extern "C" fn vc_apm_create(sample_rate: u32) -> *mut c_void {
    match Bridge::new(sample_rate) {
        Ok(bridge) => Box::into_raw(Box::new(bridge)) as *mut c_void,
        Err(()) => std::ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn vc_apm_frame_samples(handle: *mut c_void) -> usize {
    with_bridge_mut(handle, |bridge| bridge.frame_samples).unwrap_or(0)
}

#[no_mangle]
pub extern "C" fn vc_apm_process_render(
    handle: *mut c_void,
    samples: *const i16,
    len: usize,
) -> i32 {
    if samples.is_null() {
        return -100;
    }

    with_bridge_mut(handle, |bridge| {
        if len != bridge.frame_samples {
            return -101;
        }

        let input = unsafe { slice::from_raw_parts(samples, len) };
        let channel: Vec<f32> = input
            .iter()
            .map(|&sample| sample as f32 / 32768.0)
            .collect();
        let frame = vec![channel];

        match bridge.processor.analyze_render_frame(&frame) {
            Ok(()) => 0,
            Err(_) => -102,
        }
    })
    .unwrap_or(-103)
}

#[no_mangle]
pub extern "C" fn vc_apm_process_capture(
    handle: *mut c_void,
    input: *const i16,
    output: *mut i16,
    len: usize,
    delay_ms: i32,
) -> i32 {
    if input.is_null() || output.is_null() {
        return -110;
    }

    with_bridge_mut(handle, |bridge| {
        if len != bridge.frame_samples {
            return -111;
        }

        bridge.maybe_update_delay(delay_ms);

        let source = unsafe { slice::from_raw_parts(input, len) };
        let channel: Vec<f32> = source
            .iter()
            .map(|&sample| sample as f32 / 32768.0)
            .collect();
        let mut frame = vec![channel];

        if bridge.processor.process_capture_frame(&mut frame).is_err() {
            return -112;
        }

        let destination = unsafe { slice::from_raw_parts_mut(output, len) };
        for (dst, sample) in destination.iter_mut().zip(frame[0].iter().copied()) {
            let scaled = (sample.clamp(-1.0, 1.0) * 32767.0).round();
            *dst = scaled as i16;
        }

        0
    })
    .unwrap_or(-113)
}

#[no_mangle]
pub extern "C" fn vc_apm_reset(handle: *mut c_void) {
    let _ = with_bridge_mut(handle, |bridge| {
        bridge.processor.reinitialize();
        bridge.apply_config(bridge.delay_ms);
    });
}

#[no_mangle]
pub extern "C" fn vc_apm_destroy(handle: *mut c_void) {
    if handle.is_null() {
        return;
    }
    unsafe {
        drop(Box::from_raw(handle as *mut Bridge));
    }
}
