// Small, fixed-action uinput helper for the user's Hyprland session.
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int emit(int fd, unsigned short type, unsigned short code, int value) {
    struct input_event ev = { .type = type, .code = code, .value = value };
    return write(fd, &ev, sizeof(ev)) == sizeof(ev) ? 0 : -1;
}

static int sync_event(int fd) { return emit(fd, EV_SYN, SYN_REPORT, 0); }

static int tap(int fd, int code) {
    if (emit(fd, EV_KEY, code, 1) || sync_event(fd)) return -1;
    usleep(35000);
    if (emit(fd, EV_KEY, code, 0) || sync_event(fd)) return -1;
    return 0;
}

static int key_code(const char *key) {
    const struct { const char *name; int code; } keys[] = {
        {"enter", KEY_ENTER}, {"tab", KEY_TAB}, {"escape", KEY_ESC},
        {"backspace", KEY_BACKSPACE}, {"delete", KEY_DELETE},
        {"space", KEY_SPACE}, {"up", KEY_UP}, {"down", KEY_DOWN},
        {"left", KEY_LEFT}, {"right", KEY_RIGHT}, {"home", KEY_HOME},
        {"end", KEY_END}, {"pageup", KEY_PAGEUP}, {"pagedown", KEY_PAGEDOWN},
    };
    for (size_t i = 0; i < sizeof(keys) / sizeof(keys[0]); i++)
        if (!strcmp(key, keys[i].name)) return keys[i].code;
    return -1;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: wayland-input click left|right|middle|double | key NAME|ctrl-v|ctrl-a\n");
        return 2;
    }
    int code = -1, repeats = 1, modifier = 0, second_modifier = 0;
    if (!strcmp(argv[1], "click")) {
        if (!strcmp(argv[2], "left") || !strcmp(argv[2], "double")) code = BTN_LEFT;
        else if (!strcmp(argv[2], "right")) code = BTN_RIGHT;
        else if (!strcmp(argv[2], "middle")) code = BTN_MIDDLE;
        if (!strcmp(argv[2], "double")) repeats = 2;
    } else if (!strcmp(argv[1], "key")) {
        code = key_code(argv[2]);
        if (!strcmp(argv[2], "ctrl-v")) { code = KEY_V; modifier = KEY_LEFTCTRL; }
        if (!strcmp(argv[2], "ctrl-shift-v")) { code = KEY_V; modifier = KEY_LEFTCTRL; second_modifier = KEY_LEFTSHIFT; }
        if (!strcmp(argv[2], "ctrl-a")) { code = KEY_A; modifier = KEY_LEFTCTRL; }
    }
    if (code < 0) { fprintf(stderr, "unsupported input action\n"); return 2; }

    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) { perror("open /dev/uinput"); return 1; }
    int allowed[] = { BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V,
        KEY_A, KEY_ENTER, KEY_TAB, KEY_ESC, KEY_BACKSPACE, KEY_DELETE,
        KEY_SPACE, KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_HOME,
        KEY_END, KEY_PAGEUP, KEY_PAGEDOWN };
    if (ioctl(fd, UI_SET_EVBIT, EV_KEY) < 0 || ioctl(fd, UI_SET_EVBIT, EV_SYN) < 0) goto fail;
    for (size_t i = 0; i < sizeof(allowed) / sizeof(allowed[0]); i++)
        if (ioctl(fd, UI_SET_KEYBIT, allowed[i]) < 0) goto fail;
    struct uinput_setup setup = {0};
    setup.id.bustype = BUS_USB;
    setup.id.vendor = 0x1d6b;
    setup.id.product = 0x0104;
    snprintf(setup.name, sizeof(setup.name), "OpenClaw Wayland Input");
    if (ioctl(fd, UI_DEV_SETUP, &setup) < 0 || ioctl(fd, UI_DEV_CREATE) < 0) goto fail;
    usleep(550000); // Allow Hyprland to register the new virtual device.
    if (modifier && (emit(fd, EV_KEY, modifier, 1) || sync_event(fd))) goto destroy;
    if (second_modifier && (emit(fd, EV_KEY, second_modifier, 1) || sync_event(fd))) goto destroy;
    for (int i = 0; i < repeats; i++) {
        if (tap(fd, code)) goto destroy;
        if (i + 1 < repeats) usleep(80000);
    }
    if (second_modifier && (emit(fd, EV_KEY, second_modifier, 0) || sync_event(fd))) goto destroy;
    if (modifier && (emit(fd, EV_KEY, modifier, 0) || sync_event(fd))) goto destroy;
    usleep(80000);
    ioctl(fd, UI_DEV_DESTROY);
    close(fd);
    return 0;
destroy:
    ioctl(fd, UI_DEV_DESTROY);
fail:
    fprintf(stderr, "uinput action failed: %s\n", strerror(errno));
    close(fd);
    return 1;
}
