(() => {
    const endpoint = "https://cinematokyo-booking-clicks.leogopfert.workers.dev/click";

    const recordClick = event => {
        if (!event.isTrusted || event.defaultPrevented) return;
        if (event.type === "auxclick" && event.button !== 1) return;
        if (!event.target?.closest?.("a[data-booking-click]")) return;
        if (navigator.globalPrivacyControl || navigator.doNotTrack === "1") return;

        fetch(endpoint, {
            method: "POST",
            keepalive: true,
            credentials: "omit",
            referrerPolicy: "no-referrer",
        }).catch(() => {});
    };

    document.addEventListener("click", recordClick, { passive: true });
    document.addEventListener("auxclick", recordClick, { passive: true });
})();
