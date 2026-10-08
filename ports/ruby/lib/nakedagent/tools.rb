# frozen_string_literal: true

require "fileutils"
require "open3"
require_relative "pyutil"
require_relative "shlex"

module Nakedagent
  # Tools are callables (args, content, workspace) -> String. Tool-level failures are returned as text
  # (spec section 5); a raised exception is an unexpected failure the loop reports.
  MAX_OUTPUT = 8000
  DEFAULT_SHELL_TIMEOUT = 120
  IS_WIN = Gem.win_platform?

  # The non-interactive shell policy (spec section 6).
  ShellPolicy = Struct.new(:allow_shell, :allowlist, :timeout_seconds) do
    def self.default
      new(false, [], DEFAULT_SHELL_TIMEOUT)
    end
  end

  module Tools
    ROOT_RE = %r{\A(?:[A-Za-z]:)?[\\/]}
    PROTECTED = [".git", ".nakedagent"].freeze

    module_function

    def truncate(str)
      n = str.length
      return str if n <= MAX_OUTPUT

      "#{str[0, MAX_OUTPUT]}\n...[truncated, #{n - MAX_OUTPUT} more chars]"
    end

    # ---------------------------------------------------------------- path guard

    def components(path)
      path.split(IS_WIN ? %r{[\\/]} : "/").reject { |c| c.empty? || c == "." }
    end

    # Like Python's Path.resolve() (non-strict): symlinks are followed, ".." is applied after the
    # component before it is resolved, and components that do not exist are kept as written.
    def realpath_non_strict(path)
      root = path[ROOT_RE] || "/"
      cur = root
      comps = components(path[root.length..])
      links = 0
      until comps.empty?
        c = comps.shift
        if c == ".."
          cur = File.dirname(cur) unless cur == root
          next
        end
        nxt = File.join(cur, c)
        if File.symlink?(nxt)
          links += 1
          target = begin
            File.readlink(nxt)
          rescue SystemCallError
            nil
          end
          if target.nil? || links > 255
            cur = nxt
            next
          end
          if (troot = target[ROOT_RE])
            cur = troot.match?(%r{\A[\\/]\z}) ? (cur[ROOT_RE] || "/") : troot
            comps = components(target[troot.length..]) + comps
          else
            comps = components(target) + comps
          end
          next
        end
        cur = nxt
      end
      cur
    end

    def resolve_target(workspace, rel)
      ws = realpath_non_strict(File.expand_path(workspace))
      joined = rel.match?(ROOT_RE) ? rel : "#{ws}/#{rel}"
      [realpath_non_strict(joined), ws]
    end

    def inside?(target, ws)
      t = IS_WIN ? target.downcase : target
      w = IS_WIN ? ws.downcase : ws
      w = w.chomp("/") unless w.match?(%r{\A(?:[a-z]:)?/\z}i)
      t == w || t.start_with?("#{w}/") || (w.end_with?("/") && t.start_with?(w))
    end

    def protected_name(target, ws)
      rel = target[ws.chomp("/").length..].to_s.sub(%r{\A/+}, "")
      first = rel.split("/").first.to_s
      first = first.downcase if IS_WIN
      PROTECTED.include?(first) ? first : nil
    end

    def missing_path(tool)
      "Error: #{tool} tool needs a path, e.g. ```#{tool} path/to/file.py```"
    end

    # ---------------------------------------------------------------- read / write / patch

    def read(args, _content, workspace)
      p = PyUtil.strip(args)
      return missing_path("read") if p.empty?

      target, ws = resolve_target(workspace, p)
      return "Error: #{p} is outside the workspace." unless inside?(target, ws)
      return "Error: #{p} does not exist." unless File.exist?(target)

      if File.directory?(target)
        names = Dir.children(target).sort_by(&:bytes)
        return "#{p} is a directory:\n#{names.join("\n")}"
      end
      truncate(PyUtil.decode_replace(File.binread(target)))
    end

    def write(args, content, workspace)
      p = PyUtil.strip(args)
      return missing_path("write") if p.empty?

      target, ws = resolve_target(workspace, p)
      return "Error: #{p} is outside the workspace." unless inside?(target, ws)

      if (bad = protected_name(target, ws))
        return "Error: #{p} is in protected directory '#{bad}'."
      end

      FileUtils.mkdir_p(File.dirname(target))
      File.binwrite(target, content)
      "Wrote #{content.length} chars to #{p}."
    end

    class PatchError < StandardError; end

    # Splits a <<<<<<< SEARCH / ======= / >>>>>>> REPLACE block (spec 5.2). Raises PatchError if malformed.
    def split_search_replace(block)
      lines = PyUtil.splitlines(block)
      find = lambda do |from, text|
        (from...lines.length).find { |i| PyUtil.strip(lines[i]) == text } || -1
      end
      start = find.call(0, "<<<<<<< SEARCH")
      sep = start >= 0 ? find.call(start + 1, "=======") : -1
      fin = sep >= 0 ? find.call(sep + 1, ">>>>>>> REPLACE") : -1
      raise PatchError, "expected <<<<<<< SEARCH / ======= / >>>>>>> REPLACE markers, in that order" if fin < 0

      ((start + 1)...fin).each do |i|
        if PyUtil.strip(lines[i]).start_with?("<<<<<<<")
          raise PatchError, "a second <<<<<<< marker appears before the matching >>>>>>>"
        end
      end
      if lines[(fin + 1)..].any? { |l| !PyUtil.strip(l).empty? }
        raise PatchError, "unexpected content after >>>>>>> REPLACE; use one patch block per call"
      end

      [lines[(start + 1)...sep].join("\n"), lines[(sep + 1)...fin].join("\n")]
    end

    # Non-overlapping occurrences; an empty needle matches len+1 times, like Python's str.count.
    def count_occurrences(hay, needle)
      return hay.length + 1 if needle.empty?

      n = 0
      pos = hay.index(needle)
      while pos
        n += 1
        pos = hay.index(needle, pos + needle.length)
      end
      n
    end

    def patch(args, content, workspace)
      p = PyUtil.strip(args)
      return missing_path("patch") if p.empty?

      target, ws = resolve_target(workspace, p)
      return "Error: #{p} is outside the workspace." unless inside?(target, ws)

      if (bad = protected_name(target, ws))
        return "Error: #{p} is in protected directory '#{bad}'."
      end
      return "Error: #{p} does not exist. Use write to create it." unless File.exist?(target)

      begin
        search, replace = split_search_replace(content)
      rescue PatchError => e
        return "Error: malformed patch block (#{e.message})."
      end
      original = PyUtil.decode_strict(File.binread(target))
      return "Error: #{p} is not valid UTF-8; patch refused without changing the file." if original.nil?

      count = count_occurrences(original, search)
      return "Error: SEARCH text not found in #{p}. It must match exactly, including whitespace." if count.zero?
      return "Error: SEARCH text matches #{count} locations in #{p}; make it more specific." if count > 1

      at = search.empty? ? 0 : original.index(search)
      File.binwrite(target, original[0, at] + replace + original[(at + search.length)..].to_s)
      "Patched #{p}."
    end

    # ---------------------------------------------------------------- shell

    def executable_file?(file)
      File.file?(file) && (IS_WIN || File.executable?(file))
    end

    # shutil.which: a name with a directory part is checked directly, otherwise PATH is searched.
    def which(name)
      return nil if name.nil? || name.empty?

      exts = IS_WIN ? (ENV["PATHEXT"] || ".COM;.EXE;.BAT;.CMD").split(";") : [""]
      direct = name.include?("/") || (IS_WIN && name.include?("\\"))
      dirs = direct ? [""] : (ENV["PATH"] || "").split(File::PATH_SEPARATOR)
      dirs.each do |dir|
        base = direct ? name : File.join(dir.empty? ? "." : dir, name)
        candidates = if IS_WIN && exts.any? { |e| base.downcase.end_with?(e.downcase) }
                       [base]
                     else
                       exts.map { |e| base + e }
                     end
        candidates.each { |c| return c if executable_file?(c) }
      end
      nil
    end

    def shell(args, content, workspace, policy)
      cmd = PyUtil.strip(content)
      cmd = PyUtil.strip(args) if cmd.empty?
      return "Error: shell tool got no command." if cmd.empty?

      timeout = policy.timeout_seconds
      return "Error: --shell-timeout must be a positive integer." unless timeout.is_a?(Numeric) && timeout.positive?
      unless policy.allow_shell
        return "Error: shell execution blocked (non-interactive shell execution requires --allow-shell)."
      end
      unless Shlex.allowed?(cmd, policy.allowlist)
        return "Error: shell execution blocked (non-interactive command is not in --shell-allowlist)."
      end

      argv = begin
        Shlex.split(cmd)
      rescue Shlex::Error => e
        return "Error: malformed command (#{e.message})."
      end
      name = argv.first.to_s
      exe = which(name)
      if exe.nil?
        return "Error: '#{name}' is not an executable on PATH. " \
               "Non-interactive mode runs programs directly without a shell, so " \
               "shell built-ins (e.g. cmd's echo/dir) and operators (|, &&, ;) " \
               "are not available."
      end
      if IS_WIN && exe.match?(/\.(bat|cmd)\z/i) && argv[1..].any? { |a| a.match?(/[&|<>^%!"]/) }
        return "Error: shell execution blocked (cmd.exe metacharacters in arguments to a batch file); " \
               "Windows runs .bat/.cmd files through cmd.exe, which would interpret them."
      end

      run_command(exe, argv[1..], workspace, timeout)
    end

    def run_command(exe, args, workspace, timeout)
      out = err = nil
      status = nil
      timed_out = false
      begin
        # [exe, exe] is the [command, argv0] form: Ruby never hands it to a shell, even with no arguments.
        Open3.popen3([exe, exe], *args, chdir: workspace) do |stdin, stdout, stderr, wait|
          stdin.close
          readers = [Thread.new { stdout.binmode.read }, Thread.new { stderr.binmode.read }]
          if wait.join(timeout).nil?
            timed_out = true
            begin
              Process.kill("KILL", wait.pid)
            rescue SystemCallError
              nil
            end
            wait.join
          end
          out, err = readers.map(&:value)
          status = wait.value
        end
      rescue SystemCallError, IOError => e
        return "Error: command execution failed: #{e.class}: #{e.message}"
      end
      return "Error: command timed out after #{timeout}s." if timed_out

      code = status.exitstatus || -(status.termsig || 1)
      parts = ["(exit #{code})"]
      parts << PyUtil.decode_replace(out) unless out.empty?
      parts << "--- stderr ---\n#{PyUtil.decode_replace(err)}" unless err.empty?
      truncate(parts.join("\n"))
    end
  end
end
