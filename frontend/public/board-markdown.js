(function(){
  "use strict";

  function escapeHtml(text){
    var esc = document.createElement("div");
    esc.textContent = text;
    return esc.innerHTML;
  }

  function linkifyEscaped(escaped){
    return escaped.replace(/((https?:\/\/|www\.)[^\s<]+)/gi, function(match){
      var trail = "";
      var m = match.match(/[),.;:!?]+$/);
      if(m){ trail = m[0]; match = match.slice(0, match.length - trail.length); }
      var href = /^https?:\/\//i.test(match) ? match : "https://" + match;
      return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + match + "</a>" + trail;
    });
  }

  function linkify(text){
    return linkifyEscaped(escapeHtml(text));
  }

  function renderInline(text){
    var escaped = escapeHtml(text);
    var codeSpans = [];
    escaped = escaped.replace(/`([^`]+)`/g, function(_, code){
      var idx = codeSpans.length;
      codeSpans.push(code);
      return "\u0000CODE" + idx + "\u0000";
    });
    escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, function(_, label, href){
      return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + label + "</a>";
    });
    escaped = escaped.replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, "<strong>$2</strong>");
    escaped = escaped.replace(/(\*|_)(?=\S)([^*_]*?\S)\1/g, "<em>$2</em>");
    escaped = linkifyEscaped(escaped);
    escaped = escaped.replace(/\u0000CODE(\d+)\u0000/g, function(_, idx){
      return "<code>" + codeSpans[+idx] + "</code>";
    });
    return escaped;
  }

  function renderMarkdown(text){
    if(!text) return "";
    var lines = String(text).replace(/\r\n/g, "\n").split("\n");
    var html = "";
    var listStack = null;
    var paragraphBuffer = [];

    function flushParagraph(){
      if(paragraphBuffer.length){
        html += "<p>" + paragraphBuffer.map(renderInline).join("<br>") + "</p>";
        paragraphBuffer = [];
      }
    }
    function closeList(){
      if(listStack){ html += "</" + listStack + ">"; listStack = null; }
    }

    var i = 0;
    while(i < lines.length){
      var line = lines[i];

      var fence = line.match(/^\s*(```|~~~)(.*)$/);
      if(fence){
        flushParagraph(); closeList();
        var fenceMarker = fence[1];
        var codeLines = [];
        i++;
        while(i < lines.length && lines[i].indexOf(fenceMarker) !== 0){
          codeLines.push(lines[i]);
          i++;
        }
        i++;
        html += "<pre><code>" + escapeHtml(codeLines.join("\n")) + "</code></pre>";
        continue;
      }

      if(/^\s*$/.test(line)){
        flushParagraph();
        closeList();
        i++;
        continue;
      }

      var header = line.match(/^(#{1,6})\s+(.*)$/);
      if(header){
        flushParagraph(); closeList();
        var level = header[1].length;
        html += "<h" + level + ">" + renderInline(header[2]) + "</h" + level + ">";
        i++;
        continue;
      }

      if(/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)){
        flushParagraph(); closeList();
        html += "<hr>";
        i++;
        continue;
      }

      var quote = line.match(/^\s*>\s?(.*)$/);
      if(quote){
        flushParagraph(); closeList();
        var quoteLines = [quote[1]];
        i++;
        while(i < lines.length && /^\s*>\s?/.test(lines[i])){
          quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
          i++;
        }
        html += "<blockquote>" + renderInline(quoteLines.join(" ")) + "</blockquote>";
        continue;
      }

      var ul = line.match(/^\s*[-*+]\s+(.*)$/);
      if(ul){
        flushParagraph();
        if(listStack !== "ul"){ closeList(); html += "<ul>"; listStack = "ul"; }
        html += "<li>" + renderInline(ul[1]) + "</li>";
        i++;
        continue;
      }

      var ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if(ol){
        flushParagraph();
        if(listStack !== "ol"){ closeList(); html += "<ol>"; listStack = "ol"; }
        html += "<li>" + renderInline(ol[1]) + "</li>";
        i++;
        continue;
      }

      closeList();
      paragraphBuffer.push(line);
      i++;
    }
    flushParagraph();
    closeList();
    return html;
  }

  window.BoardMarkdown = {
    escapeHtml: escapeHtml,
    linkify: linkify,
    renderMarkdown: renderMarkdown
  };
})();
