const siteOrigin = "https://cinematokyo.com";

export default {
    fetch: (request, env) => {
        const url = new URL(request.url);
        if (url.pathname !== "/click" || request.method !== "POST") {
            return new Response(null, { status: 404 });
        }
        if (request.headers.get("Origin") !== siteOrigin) {
            return new Response(null, { status: 403 });
        }

        return env.BOOKING_CLICKS.prepare(
            "INSERT INTO daily_booking_clicks (day, clicks) VALUES (date('now', '+9 hours'), 1) " +
            "ON CONFLICT(day) DO UPDATE SET clicks = clicks + 1"
        ).run().then(() => new Response(null, {
            status: 204,
            headers: {
                "Access-Control-Allow-Origin": siteOrigin,
                "Cache-Control": "no-store",
            },
        }));
    },
};
