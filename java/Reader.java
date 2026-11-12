/**
 * The Java half of the reader bench.
 *
 * Speaks the line protocol in `mojibake_tests/bridge.py`: one request JSON per stdin line, one
 * `@@ENC@@`-prefixed response line per request, replies serialized and tagged with the request id.
 *
 * `E::text` means what it means everywhere else in this lab: the direct child TEXT NODES of E.
 * jsoup calls them `Element.textNodes()`, and `getWholeText()` is the undecorated data — `text()`
 * would collapse whitespace and so would answer a different question from every other column.
 */
import java.io.ByteArrayInputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpHeaders;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.Flow;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.net.ssl.SSLSession;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.nodes.TextNode;

public final class Reader {
    /** The shape of the URL serve.py hands out, so any base-uri-dependent behaviour is realistic. */
    private static final String CASE_URL = "http://127.0.0.1:8765/c/case";
    private static final Gson GSON = new Gson();
    private static final Pattern PSEUDO = Pattern.compile("^(.*?)(?:::text|::attr\\((.+)\\))$");

    // ------------------------------------------------------------ selector plumbing
    private static String[] splitPseudo(String sel) {
        Matcher m = PSEUDO.matcher(sel);
        if (!m.matches()) return new String[] {sel.trim().isEmpty() ? "*" : sel.trim(), "text", null};
        String base = m.group(1).trim();
        return new String[] {base.isEmpty() ? "*" : base, m.group(2) != null ? "attr" : "text",
                             m.group(2)};
    }

    private static List<String> extract(Document doc, String sel) {
        String[] parts = splitPseudo(sel);
        List<String> out = new ArrayList<>();
        for (Element el : doc.select(parts[0])) {
            if ("attr".equals(parts[1])) {
                if (el.hasAttr(parts[2])) out.add(el.attr(parts[2]));
            } else {
                for (TextNode t : el.textNodes()) out.add(t.getWholeText());
            }
        }
        return out;
    }

    private static String charsetOf(String ctype) {
        if (ctype == null) return null;
        Matcher m = Pattern.compile("charset\\s*=\\s*([^;\\s]+)", Pattern.CASE_INSENSITIVE)
                           .matcher(ctype);
        return m.find() ? m.group(1).replaceAll("^[\"']|[\"']$", "") : null;
    }

    // ------------------------------------------------------------ the JDK's own body decoding
    /**
     * `HttpResponse.BodyHandlers.ofString()` decides the charset itself, from the Content-Type
     * header, falling back to UTF-8 — and that decision is what a Java scraper actually gets. It
     * is reachable without a socket: a BodyHandler is a function from ResponseInfo to a
     * BodySubscriber, and a BodySubscriber is fed bytes by hand.
     */
    private static String jdkBodyToString(String ctype, byte[] body) throws Exception {
        HttpHeaders headers = HttpHeaders.of(
                Map.of("Content-Type", List.of(ctype == null ? "text/html" : ctype)),
                (a, b) -> true);
        HttpResponse.ResponseInfo info = new HttpResponse.ResponseInfo() {
            public int statusCode() { return 200; }
            public HttpHeaders headers() { return headers; }
            public HttpClient.Version version() { return HttpClient.Version.HTTP_1_1; }
        };
        HttpResponse.BodySubscriber<String> sub = HttpResponse.BodyHandlers.ofString().apply(info);
        sub.onSubscribe(new Flow.Subscription() {
            public void request(long n) { }
            public void cancel() { }
        });
        sub.onNext(List.of(ByteBuffer.wrap(body)));
        sub.onComplete();
        return sub.getBody().toCompletableFuture().get();
    }

    // ------------------------------------------------------------ the stacks
    private static List<String> run(String stack, String ctype, byte[] body, String sel)
            throws Exception {
        switch (stack) {
            // jsoup deciding for itself: BOM, then its own <meta charset> prescan over the first
            // chunk it reads, then UTF-8. This is `Jsoup.parse(File)` and every offline parse.
            case "jsoup(bytes)":
                return extract(Jsoup.parse(new ByteArrayInputStream(body), null, CASE_URL), sel);

            // What `Jsoup.connect(url).get()` does: the HTTP charset, when the server declared one,
            // is handed in and jsoup does NOT then look at the document.
            case "jsoup(http-charset)":
                return extract(Jsoup.parse(new ByteArrayInputStream(body), charsetOf(ctype),
                                           CASE_URL), sel);

            // java.net.http + jsoup: the JDK turns bytes into a String on its own rules, and jsoup
            // parsing a String has no bytes left to sniff.
            case "jdk-http.ofString+jsoup":
                return extract(Jsoup.parse(jdkBodyToString(ctype, body), CASE_URL), sel);

            default:
                throw new IllegalArgumentException("no such stack: " + stack);
        }
    }

    private static final String[] STACKS =
            {"jsoup(bytes)", "jsoup(http-charset)", "jdk-http.ofString+jsoup"};

    // ------------------------------------------------------------ the line protocol
    public static void main(String[] args) throws Exception {
        PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
        java.io.BufferedReader in = new java.io.BufferedReader(
                new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line = in.readLine()) != null) {
            if (line.trim().isEmpty()) continue;
            JsonObject reply = new JsonObject();
            try {
                JsonObject req = GSON.fromJson(line, JsonObject.class);
                if (req.has("id")) reply.add("id", req.get("id"));
                if (req.has("op") && "stacks".equals(req.get("op").getAsString())) {
                    reply.add("stacks", GSON.toJsonTree(STACKS));
                } else {
                    byte[] body = Base64.getDecoder().decode(req.get("body").getAsString());
                    String ctype = req.get("ctype").isJsonNull() ? null
                                                                 : req.get("ctype").getAsString();
                    reply.add("values", GSON.toJsonTree(run(req.get("stack").getAsString(), ctype,
                                                            body, req.get("sel").getAsString())));
                }
            } catch (Throwable e) {
                // A stack that refuses has told you something; it must reach the matrix, not the
                // exit code.
                String msg = e.getMessage() == null ? e.toString() : e.getMessage();
                reply.addProperty("error", e.getClass().getSimpleName() + ": " + msg);
            }
            out.print("@@ENC@@" + GSON.toJson(reply) + "\n");
            out.flush();
        }
    }
}
