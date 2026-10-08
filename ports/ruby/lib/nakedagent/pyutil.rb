# frozen_string_literal: true

module Nakedagent
  # Helpers that reproduce the few Python string behaviours the reference relies on, so the
  # port matches it exactly. Lengths are in code points (String#length on valid UTF-8).
  module PyUtil
    # Python str.isspace(): ASCII whitespace, U+001C..U+001F, NEL, NBSP and the Unicode space separators.
    SPACE_CLASS = "[\\t-\\r\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]"
    LEADING_SPACE = Regexp.new("\\A#{SPACE_CLASS}+")
    TRAILING_SPACE = Regexp.new("#{SPACE_CLASS}+\\z")
    LINE_BREAK = Regexp.new("\\r\\n|[\\n\\r\\v\\f\\u001c-\\u001e\\u0085\\u2028\\u2029]")

    module_function

    def rstrip(str)
      str.sub(TRAILING_SPACE, "")
    end

    def strip(str)
      rstrip(str.sub(LEADING_SPACE, ""))
    end

    # Python str.splitlines(): splits on more than LF (spec section 11, quirk 3).
    def splitlines(str)
      out = []
      pos = 0
      while (m = LINE_BREAK.match(str, pos))
        out << str[pos...m.begin(0)]
        pos = m.end(0)
      end
      out << str[pos..] if pos < str.length
      out
    end

    # bytes.decode("utf-8", errors="replace")
    def decode_replace(bytes)
      bytes.dup.force_encoding(Encoding::UTF_8).scrub("�")
    end

    # Strict UTF-8 decode; nil if the bytes are not valid UTF-8.
    def decode_strict(bytes)
      str = bytes.dup.force_encoding(Encoding::UTF_8)
      str.valid_encoding? ? str : nil
    end

    # repr() for plain strings, enough for error messages.
    def repr(str)
      q = "'"
      q = '"' if str.include?("'") && !str.include?('"')
      out = +q
      str.each_char do |ch|
        c = ch.ord
        out << if ch == q || ch == "\\" then "\\#{ch}"
               elsif ch == "\n" then "\\n"
               elsif ch == "\r" then "\\r"
               elsif ch == "\t" then "\\t"
               elsif c < 0x20 || c == 0x7f then format("\\x%02x", c)
               else ch
               end
      end
      out << q
    end
  end
end
