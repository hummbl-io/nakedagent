# frozen_string_literal: true

require_relative "nakedagent/pyutil"
require_relative "nakedagent/toolcall"
require_relative "nakedagent/shlex"
require_relative "nakedagent/tools"
require_relative "nakedagent/prompt"
require_relative "nakedagent/llm"
require_relative "nakedagent/loop"

# nakedagent for Ruby: the foundation of spec v0.1, standard library only.
module Nakedagent
  VERSION = "0.1.0-dev"
end
