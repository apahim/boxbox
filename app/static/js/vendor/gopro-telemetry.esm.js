var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __require = /* @__PURE__ */ ((x) => typeof require !== "undefined" ? require : typeof Proxy !== "undefined" ? new Proxy(x, {
  get: (a, b) => (typeof require !== "undefined" ? require : a)[b]
}) : x)(function(x) {
  if (typeof require !== "undefined") return require.apply(this, arguments);
  throw Error('Dynamic require of "' + x + '" is not supported');
});
var __commonJS = (cb, mod) => function __require2() {
  return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));

// node_modules/binary-parser/dist/binary_parser.js
var require_binary_parser = __commonJS({
  "node_modules/binary-parser/dist/binary_parser.js"(exports) {
    "use strict";
    Object.defineProperty(exports, "__esModule", { value: true });
    exports.Parser = void 0;
    var Context = class {
      constructor(importPath, useContextVariables) {
        this.code = "";
        this.scopes = [["vars"]];
        this.bitFields = [];
        this.tmpVariableCount = 0;
        this.references = /* @__PURE__ */ new Map();
        this.imports = [];
        this.reverseImports = /* @__PURE__ */ new Map();
        this.useContextVariables = false;
        this.importPath = importPath;
        this.useContextVariables = useContextVariables;
      }
      generateVariable(name) {
        const scopes = [...this.scopes[this.scopes.length - 1]];
        if (name) {
          scopes.push(name);
        }
        return scopes.join(".");
      }
      generateOption(val) {
        switch (typeof val) {
          case "number":
            return val.toString();
          case "string":
            return this.generateVariable(val);
          case "function":
            return `${this.addImport(val)}.call(${this.generateVariable()}, vars)`;
        }
      }
      generateError(err) {
        this.pushCode(`throw new Error(${err});`);
      }
      generateTmpVariable() {
        return "$tmp" + this.tmpVariableCount++;
      }
      pushCode(code) {
        this.code += code + "\n";
      }
      pushPath(name) {
        if (name) {
          this.scopes[this.scopes.length - 1].push(name);
        }
      }
      popPath(name) {
        if (name) {
          this.scopes[this.scopes.length - 1].pop();
        }
      }
      pushScope(name) {
        this.scopes.push([name]);
      }
      popScope() {
        this.scopes.pop();
      }
      addImport(im) {
        if (!this.importPath)
          return `(${im})`;
        let id = this.reverseImports.get(im);
        if (!id) {
          id = this.imports.push(im) - 1;
          this.reverseImports.set(im, id);
        }
        return `${this.importPath}[${id}]`;
      }
      addReference(alias) {
        if (!this.references.has(alias)) {
          this.references.set(alias, { resolved: false, requested: false });
        }
      }
      markResolved(alias) {
        const reference = this.references.get(alias);
        if (reference) {
          reference.resolved = true;
        }
      }
      markRequested(aliasList) {
        aliasList.forEach((alias) => {
          const reference = this.references.get(alias);
          if (reference) {
            reference.requested = true;
          }
        });
      }
      getUnresolvedReferences() {
        return Array.from(this.references).filter(([_, reference]) => !reference.resolved && !reference.requested).map(([alias, _]) => alias);
      }
    };
    var aliasRegistry = /* @__PURE__ */ new Map();
    var FUNCTION_PREFIX = "___parser_";
    var PRIMITIVE_SIZES = {
      uint8: 1,
      uint16le: 2,
      uint16be: 2,
      uint32le: 4,
      uint32be: 4,
      int8: 1,
      int16le: 2,
      int16be: 2,
      int32le: 4,
      int32be: 4,
      int64be: 8,
      int64le: 8,
      uint64be: 8,
      uint64le: 8,
      floatle: 4,
      floatbe: 4,
      doublele: 8,
      doublebe: 8
    };
    var PRIMITIVE_NAMES = {
      uint8: "Uint8",
      uint16le: "Uint16",
      uint16be: "Uint16",
      uint32le: "Uint32",
      uint32be: "Uint32",
      int8: "Int8",
      int16le: "Int16",
      int16be: "Int16",
      int32le: "Int32",
      int32be: "Int32",
      int64be: "BigInt64",
      int64le: "BigInt64",
      uint64be: "BigUint64",
      uint64le: "BigUint64",
      floatle: "Float32",
      floatbe: "Float32",
      doublele: "Float64",
      doublebe: "Float64"
    };
    var PRIMITIVE_LITTLE_ENDIANS = {
      uint8: false,
      uint16le: true,
      uint16be: false,
      uint32le: true,
      uint32be: false,
      int8: false,
      int16le: true,
      int16be: false,
      int32le: true,
      int32be: false,
      int64be: false,
      int64le: true,
      uint64be: false,
      uint64le: true,
      floatle: true,
      floatbe: false,
      doublele: true,
      doublebe: false
    };
    var Parser = class _Parser {
      constructor() {
        this.varName = "";
        this.type = "";
        this.options = {};
        this.endian = "be";
        this.useContextVariables = false;
      }
      static start() {
        return new _Parser();
      }
      sanitizeFieldName(name) {
        if (name && !/^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(name)) {
          throw new Error(`Invalid field name: ${name}`);
        }
        return name;
      }
      sanitizeEncoding(encoding) {
        const allowed = [
          "utf8",
          "utf-8",
          "ascii",
          "hex",
          "base64",
          "base64url",
          "latin1",
          "binary"
        ];
        if (!allowed.includes(encoding.toLowerCase())) {
          throw new Error(`Invalid encoding: ${encoding}`);
        }
        return encoding;
      }
      primitiveGenerateN(type, ctx) {
        const typeName = PRIMITIVE_NAMES[type];
        const littleEndian = PRIMITIVE_LITTLE_ENDIANS[type];
        ctx.pushCode(`${ctx.generateVariable(this.varName)} = dataView.get${typeName}(offset, ${littleEndian});`);
        ctx.pushCode(`offset += ${PRIMITIVE_SIZES[type]};`);
      }
      primitiveN(type, varName, options) {
        return this.setNextParser(type, varName, options);
      }
      useThisEndian(type) {
        return type + this.endian.toLowerCase();
      }
      uint8(varName, options = {}) {
        return this.primitiveN("uint8", varName, options);
      }
      uint16(varName, options = {}) {
        return this.primitiveN(this.useThisEndian("uint16"), varName, options);
      }
      uint16le(varName, options = {}) {
        return this.primitiveN("uint16le", varName, options);
      }
      uint16be(varName, options = {}) {
        return this.primitiveN("uint16be", varName, options);
      }
      uint32(varName, options = {}) {
        return this.primitiveN(this.useThisEndian("uint32"), varName, options);
      }
      uint32le(varName, options = {}) {
        return this.primitiveN("uint32le", varName, options);
      }
      uint32be(varName, options = {}) {
        return this.primitiveN("uint32be", varName, options);
      }
      int8(varName, options = {}) {
        return this.primitiveN("int8", varName, options);
      }
      int16(varName, options = {}) {
        return this.primitiveN(this.useThisEndian("int16"), varName, options);
      }
      int16le(varName, options = {}) {
        return this.primitiveN("int16le", varName, options);
      }
      int16be(varName, options = {}) {
        return this.primitiveN("int16be", varName, options);
      }
      int32(varName, options = {}) {
        return this.primitiveN(this.useThisEndian("int32"), varName, options);
      }
      int32le(varName, options = {}) {
        return this.primitiveN("int32le", varName, options);
      }
      int32be(varName, options = {}) {
        return this.primitiveN("int32be", varName, options);
      }
      bigIntVersionCheck() {
        if (!DataView.prototype.getBigInt64)
          throw new Error("BigInt64 is unsupported on this runtime");
      }
      int64(varName, options = {}) {
        this.bigIntVersionCheck();
        return this.primitiveN(this.useThisEndian("int64"), varName, options);
      }
      int64be(varName, options = {}) {
        this.bigIntVersionCheck();
        return this.primitiveN("int64be", varName, options);
      }
      int64le(varName, options = {}) {
        this.bigIntVersionCheck();
        return this.primitiveN("int64le", varName, options);
      }
      uint64(varName, options = {}) {
        this.bigIntVersionCheck();
        return this.primitiveN(this.useThisEndian("uint64"), varName, options);
      }
      uint64be(varName, options = {}) {
        this.bigIntVersionCheck();
        return this.primitiveN("uint64be", varName, options);
      }
      uint64le(varName, options = {}) {
        this.bigIntVersionCheck();
        return this.primitiveN("uint64le", varName, options);
      }
      floatle(varName, options = {}) {
        return this.primitiveN("floatle", varName, options);
      }
      floatbe(varName, options = {}) {
        return this.primitiveN("floatbe", varName, options);
      }
      doublele(varName, options = {}) {
        return this.primitiveN("doublele", varName, options);
      }
      doublebe(varName, options = {}) {
        return this.primitiveN("doublebe", varName, options);
      }
      bitN(size, varName, options) {
        options.length = size;
        return this.setNextParser("bit", varName, options);
      }
      bit1(varName, options = {}) {
        return this.bitN(1, varName, options);
      }
      bit2(varName, options = {}) {
        return this.bitN(2, varName, options);
      }
      bit3(varName, options = {}) {
        return this.bitN(3, varName, options);
      }
      bit4(varName, options = {}) {
        return this.bitN(4, varName, options);
      }
      bit5(varName, options = {}) {
        return this.bitN(5, varName, options);
      }
      bit6(varName, options = {}) {
        return this.bitN(6, varName, options);
      }
      bit7(varName, options = {}) {
        return this.bitN(7, varName, options);
      }
      bit8(varName, options = {}) {
        return this.bitN(8, varName, options);
      }
      bit9(varName, options = {}) {
        return this.bitN(9, varName, options);
      }
      bit10(varName, options = {}) {
        return this.bitN(10, varName, options);
      }
      bit11(varName, options = {}) {
        return this.bitN(11, varName, options);
      }
      bit12(varName, options = {}) {
        return this.bitN(12, varName, options);
      }
      bit13(varName, options = {}) {
        return this.bitN(13, varName, options);
      }
      bit14(varName, options = {}) {
        return this.bitN(14, varName, options);
      }
      bit15(varName, options = {}) {
        return this.bitN(15, varName, options);
      }
      bit16(varName, options = {}) {
        return this.bitN(16, varName, options);
      }
      bit17(varName, options = {}) {
        return this.bitN(17, varName, options);
      }
      bit18(varName, options = {}) {
        return this.bitN(18, varName, options);
      }
      bit19(varName, options = {}) {
        return this.bitN(19, varName, options);
      }
      bit20(varName, options = {}) {
        return this.bitN(20, varName, options);
      }
      bit21(varName, options = {}) {
        return this.bitN(21, varName, options);
      }
      bit22(varName, options = {}) {
        return this.bitN(22, varName, options);
      }
      bit23(varName, options = {}) {
        return this.bitN(23, varName, options);
      }
      bit24(varName, options = {}) {
        return this.bitN(24, varName, options);
      }
      bit25(varName, options = {}) {
        return this.bitN(25, varName, options);
      }
      bit26(varName, options = {}) {
        return this.bitN(26, varName, options);
      }
      bit27(varName, options = {}) {
        return this.bitN(27, varName, options);
      }
      bit28(varName, options = {}) {
        return this.bitN(28, varName, options);
      }
      bit29(varName, options = {}) {
        return this.bitN(29, varName, options);
      }
      bit30(varName, options = {}) {
        return this.bitN(30, varName, options);
      }
      bit31(varName, options = {}) {
        return this.bitN(31, varName, options);
      }
      bit32(varName, options = {}) {
        return this.bitN(32, varName, options);
      }
      namely(alias) {
        aliasRegistry.set(alias, this);
        this.alias = alias;
        return this;
      }
      skip(length, options = {}) {
        return this.seek(length, options);
      }
      seek(relOffset, options = {}) {
        if (options.assert) {
          throw new Error("assert option on seek is not allowed.");
        }
        return this.setNextParser("seek", "", { length: relOffset });
      }
      string(varName, options) {
        if (!options.zeroTerminated && !options.length && !options.greedy) {
          throw new Error("One of length, zeroTerminated, or greedy must be defined for string.");
        }
        if ((options.zeroTerminated || options.length) && options.greedy) {
          throw new Error("greedy is mutually exclusive with length and zeroTerminated for string.");
        }
        if (options.stripNull && !(options.length || options.greedy)) {
          throw new Error("length or greedy must be defined if stripNull is enabled.");
        }
        options.encoding = options.encoding || "utf8";
        this.sanitizeEncoding(options.encoding);
        return this.setNextParser("string", varName, options);
      }
      buffer(varName, options) {
        if (!options.length && !options.readUntil) {
          throw new Error("length or readUntil must be defined for buffer.");
        }
        return this.setNextParser("buffer", varName, options);
      }
      wrapped(varName, options) {
        if (typeof options !== "object" && typeof varName === "object") {
          options = varName;
          varName = "";
        }
        if (!options || !options.wrapper || !options.type) {
          throw new Error("Both wrapper and type must be defined for wrapped.");
        }
        if (!options.length && !options.readUntil) {
          throw new Error("length or readUntil must be defined for wrapped.");
        }
        return this.setNextParser("wrapper", varName, options);
      }
      array(varName, options) {
        if (!options.readUntil && !options.length && !options.lengthInBytes) {
          throw new Error("One of readUntil, length and lengthInBytes must be defined for array.");
        }
        if (!options.type) {
          throw new Error("type is required for array.");
        }
        if (typeof options.type === "string" && !aliasRegistry.has(options.type) && !(options.type in PRIMITIVE_SIZES)) {
          throw new Error(`Array element type "${options.type}" is unknown.`);
        }
        return this.setNextParser("array", varName, options);
      }
      choice(varName, options) {
        if (typeof options !== "object" && typeof varName === "object") {
          options = varName;
          varName = "";
        }
        if (!options) {
          throw new Error("tag and choices are are required for choice.");
        }
        if (!options.tag) {
          throw new Error("tag is requird for choice.");
        }
        if (!options.choices) {
          throw new Error("choices is required for choice.");
        }
        for (const keyString in options.choices) {
          const key = parseInt(keyString, 10);
          const value = options.choices[key];
          if (isNaN(key)) {
            throw new Error(`Choice key "${keyString}" is not a number.`);
          }
          if (typeof value === "string" && !aliasRegistry.has(value) && !(value in PRIMITIVE_SIZES)) {
            throw new Error(`Choice type "${value}" is unknown.`);
          }
        }
        return this.setNextParser("choice", varName, options);
      }
      nest(varName, options) {
        if (typeof options !== "object" && typeof varName === "object") {
          options = varName;
          varName = "";
        }
        if (!options || !options.type) {
          throw new Error("type is required for nest.");
        }
        if (!(options.type instanceof _Parser) && !aliasRegistry.has(options.type)) {
          throw new Error("type must be a known parser name or a Parser object.");
        }
        if (!(options.type instanceof _Parser) && !varName) {
          throw new Error("type must be a Parser object if the variable name is omitted.");
        }
        return this.setNextParser("nest", varName, options);
      }
      pointer(varName, options) {
        if (options.offset == null) {
          throw new Error("offset is required for pointer.");
        }
        if (!options.type) {
          throw new Error("type is required for pointer.");
        }
        if (typeof options.type === "string" && !(options.type in PRIMITIVE_SIZES) && !aliasRegistry.has(options.type)) {
          throw new Error(`Pointer type "${options.type}" is unknown.`);
        }
        return this.setNextParser("pointer", varName, options);
      }
      saveOffset(varName, options = {}) {
        return this.setNextParser("saveOffset", varName, options);
      }
      endianness(endianness) {
        switch (endianness.toLowerCase()) {
          case "little":
            this.endian = "le";
            break;
          case "big":
            this.endian = "be";
            break;
          default:
            throw new Error('endianness must be one of "little" or "big"');
        }
        return this;
      }
      endianess(endianess) {
        return this.endianness(endianess);
      }
      useContextVars(useContextVariables = true) {
        this.useContextVariables = useContextVariables;
        return this;
      }
      create(constructorFn) {
        if (!(constructorFn instanceof Function)) {
          throw new Error("Constructor must be a Function object.");
        }
        this.constructorFn = constructorFn;
        return this;
      }
      getContext(importPath) {
        const ctx = new Context(importPath, this.useContextVariables);
        ctx.pushCode("var dataView = new DataView(buffer.buffer, buffer.byteOffset, buffer.length);");
        if (!this.alias) {
          this.addRawCode(ctx);
        } else {
          this.addAliasedCode(ctx);
          ctx.pushCode(`return ${FUNCTION_PREFIX + this.alias}(0).result;`);
        }
        return ctx;
      }
      getCode() {
        const importPath = "imports";
        return this.getContext(importPath).code;
      }
      addRawCode(ctx) {
        ctx.pushCode("var offset = 0;");
        ctx.pushCode(`var vars = ${this.constructorFn ? "new constructorFn()" : "{}"};`);
        ctx.pushCode("vars.$parent = null;");
        ctx.pushCode("vars.$root = vars;");
        this.generate(ctx);
        this.resolveReferences(ctx);
        ctx.pushCode("delete vars.$parent;");
        ctx.pushCode("delete vars.$root;");
        ctx.pushCode("return vars;");
      }
      addAliasedCode(ctx) {
        ctx.pushCode(`function ${FUNCTION_PREFIX + this.alias}(offset, context) {`);
        ctx.pushCode(`var vars = ${this.constructorFn ? "new constructorFn()" : "{}"};`);
        ctx.pushCode("var ctx = Object.assign({$parent: null, $root: vars}, context || {});");
        ctx.pushCode(`vars = Object.assign(vars, ctx);`);
        this.generate(ctx);
        ctx.markResolved(this.alias);
        this.resolveReferences(ctx);
        ctx.pushCode("Object.keys(ctx).forEach(function (item) { delete vars[item]; });");
        ctx.pushCode("return { offset: offset, result: vars };");
        ctx.pushCode("}");
        return ctx;
      }
      resolveReferences(ctx) {
        const references = ctx.getUnresolvedReferences();
        ctx.markRequested(references);
        references.forEach((alias) => {
          var _a;
          (_a = aliasRegistry.get(alias)) === null || _a === void 0 ? void 0 : _a.addAliasedCode(ctx);
        });
      }
      compile() {
        const importPath = "imports";
        const ctx = this.getContext(importPath);
        this.compiled = new Function(importPath, "TextDecoder", `return function (buffer, constructorFn) { ${ctx.code} };`)(ctx.imports, TextDecoder);
      }
      sizeOf() {
        let size = NaN;
        if (Object.keys(PRIMITIVE_SIZES).indexOf(this.type) >= 0) {
          size = PRIMITIVE_SIZES[this.type];
        } else if (this.type === "string" && typeof this.options.length === "number") {
          size = this.options.length;
        } else if (this.type === "buffer" && typeof this.options.length === "number") {
          size = this.options.length;
        } else if (this.type === "array" && typeof this.options.length === "number") {
          let elementSize = NaN;
          if (typeof this.options.type === "string") {
            elementSize = PRIMITIVE_SIZES[this.options.type];
          } else if (this.options.type instanceof _Parser) {
            elementSize = this.options.type.sizeOf();
          }
          size = this.options.length * elementSize;
        } else if (this.type === "seek") {
          size = this.options.length;
        } else if (this.type === "nest") {
          size = this.options.type.sizeOf();
        } else if (!this.type) {
          size = 0;
        }
        if (this.next) {
          size += this.next.sizeOf();
        }
        return size;
      }
      // Follow the parser chain till the root and start parsing from there
      parse(buffer) {
        if (!this.compiled) {
          this.compile();
        }
        return this.compiled(buffer, this.constructorFn);
      }
      setNextParser(type, varName, options) {
        const parser = new _Parser();
        parser.type = type;
        parser.varName = this.sanitizeFieldName(varName);
        parser.options = options;
        parser.endian = this.endian;
        if (this.head) {
          this.head.next = parser;
        } else {
          this.next = parser;
        }
        this.head = parser;
        return this;
      }
      // Call code generator for this parser
      generate(ctx) {
        if (this.type) {
          switch (this.type) {
            case "uint8":
            case "uint16le":
            case "uint16be":
            case "uint32le":
            case "uint32be":
            case "int8":
            case "int16le":
            case "int16be":
            case "int32le":
            case "int32be":
            case "int64be":
            case "int64le":
            case "uint64be":
            case "uint64le":
            case "floatle":
            case "floatbe":
            case "doublele":
            case "doublebe":
              this.primitiveGenerateN(this.type, ctx);
              break;
            case "bit":
              this.generateBit(ctx);
              break;
            case "string":
              this.generateString(ctx);
              break;
            case "buffer":
              this.generateBuffer(ctx);
              break;
            case "seek":
              this.generateSeek(ctx);
              break;
            case "nest":
              this.generateNest(ctx);
              break;
            case "array":
              this.generateArray(ctx);
              break;
            case "choice":
              this.generateChoice(ctx);
              break;
            case "pointer":
              this.generatePointer(ctx);
              break;
            case "saveOffset":
              this.generateSaveOffset(ctx);
              break;
            case "wrapper":
              this.generateWrapper(ctx);
              break;
          }
          if (this.type !== "bit")
            this.generateAssert(ctx);
        }
        const varName = ctx.generateVariable(this.varName);
        if (this.options.formatter && this.type !== "bit") {
          this.generateFormatter(ctx, varName, this.options.formatter);
        }
        return this.generateNext(ctx);
      }
      generateAssert(ctx) {
        if (!this.options.assert) {
          return;
        }
        const varName = ctx.generateVariable(this.varName);
        switch (typeof this.options.assert) {
          case "function":
            {
              const func = ctx.addImport(this.options.assert);
              ctx.pushCode(`if (!${func}.call(vars, ${varName})) {`);
            }
            break;
          case "number":
            ctx.pushCode(`if (${this.options.assert} !== ${varName}) {`);
            break;
          case "string":
            ctx.pushCode(`if (${JSON.stringify(this.options.assert)} !== ${varName}) {`);
            break;
          default:
            throw new Error("assert option must be a string, number or a function.");
        }
        ctx.generateError(`"Assertion error: ${varName} is " + ${JSON.stringify(this.options.assert.toString())}`);
        ctx.pushCode("}");
      }
      // Recursively call code generators and append results
      generateNext(ctx) {
        if (this.next) {
          ctx = this.next.generate(ctx);
        }
        return ctx;
      }
      nextNotBit() {
        if (this.next) {
          if (this.next.type === "nest") {
            if (this.next.options && this.next.options.type instanceof _Parser) {
              if (this.next.options.type.next) {
                return this.next.options.type.next.type !== "bit";
              }
              return false;
            } else {
              return true;
            }
          } else {
            return this.next.type !== "bit";
          }
        } else {
          return true;
        }
      }
      generateBit(ctx) {
        const parser = JSON.parse(JSON.stringify(this));
        parser.options = this.options;
        parser.generateAssert = this.generateAssert.bind(this);
        parser.generateFormatter = this.generateFormatter.bind(this);
        parser.varName = ctx.generateVariable(parser.varName);
        ctx.bitFields.push(parser);
        if (!this.next || this.nextNotBit()) {
          const val = ctx.generateTmpVariable();
          ctx.pushCode(`var ${val} = 0;`);
          const getMaxBits = (from = 0) => {
            let sum2 = 0;
            for (let i = from; i < ctx.bitFields.length; i++) {
              const length = ctx.bitFields[i].options.length;
              if (sum2 + length > 32)
                break;
              sum2 += length;
            }
            return sum2;
          };
          const getBytes = (sum2) => {
            if (sum2 <= 8) {
              ctx.pushCode(`${val} = dataView.getUint8(offset);`);
              sum2 = 8;
            } else if (sum2 <= 16) {
              ctx.pushCode(`${val} = dataView.getUint16(offset);`);
              sum2 = 16;
            } else if (sum2 <= 24) {
              ctx.pushCode(`${val} = (dataView.getUint16(offset) << 8) | dataView.getUint8(offset + 2);`);
              sum2 = 24;
            } else {
              ctx.pushCode(`${val} = dataView.getUint32(offset);`);
              sum2 = 32;
            }
            ctx.pushCode(`offset += ${sum2 / 8};`);
            return sum2;
          };
          let bitOffset = 0;
          const isBigEndian = this.endian === "be";
          let sum = 0;
          let rem = 0;
          ctx.bitFields.forEach((parser2, i) => {
            let length = parser2.options.length;
            if (length > rem) {
              if (rem) {
                const mask2 = -1 >>> 32 - rem;
                ctx.pushCode(`${parser2.varName} = (${val} & 0x${mask2.toString(16)}) << ${length - rem};`);
                length -= rem;
              }
              bitOffset = 0;
              rem = sum = getBytes(getMaxBits(i) - rem);
            }
            const offset = isBigEndian ? sum - bitOffset - length : bitOffset;
            const mask = -1 >>> 32 - length;
            ctx.pushCode(`${parser2.varName} ${length < parser2.options.length ? "|=" : "="} ${val} >> ${offset} & 0x${mask.toString(16)};`);
            if (parser2.options.length === 32) {
              ctx.pushCode(`${parser2.varName} >>>= 0`);
            }
            if (parser2.options.assert) {
              parser2.generateAssert(ctx);
            }
            if (parser2.options.formatter) {
              parser2.generateFormatter(ctx, parser2.varName, parser2.options.formatter);
            }
            bitOffset += length;
            rem -= length;
          });
          ctx.bitFields = [];
        }
      }
      generateSeek(ctx) {
        const length = ctx.generateOption(this.options.length);
        ctx.pushCode(`offset += ${length};`);
      }
      generateString(ctx) {
        const name = ctx.generateVariable(this.varName);
        const start = ctx.generateTmpVariable();
        const encoding = this.options.encoding;
        const isHex = encoding.toLowerCase() === "hex";
        const toHex = 'b => b.toString(16).padStart(2, "0")';
        if (this.options.length && this.options.zeroTerminated) {
          const len = this.options.length;
          ctx.pushCode(`var ${start} = offset;`);
          ctx.pushCode(`while(dataView.getUint8(offset++) !== 0 && offset - ${start} < ${len});`);
          const end = `offset - ${start} < ${len} ? offset - 1 : offset`;
          ctx.pushCode(isHex ? `${name} = Array.from(buffer.subarray(${start}, ${end}), ${toHex}).join('');` : `${name} = new TextDecoder('${encoding}').decode(buffer.subarray(${start}, ${end}));`);
        } else if (this.options.length) {
          const len = ctx.generateOption(this.options.length);
          ctx.pushCode(isHex ? `${name} = Array.from(buffer.subarray(offset, offset + ${len}), ${toHex}).join('');` : `${name} = new TextDecoder('${encoding}').decode(buffer.subarray(offset, offset + ${len}));`);
          ctx.pushCode(`offset += ${len};`);
        } else if (this.options.zeroTerminated) {
          ctx.pushCode(`var ${start} = offset;`);
          ctx.pushCode("while(dataView.getUint8(offset++) !== 0);");
          ctx.pushCode(isHex ? `${name} = Array.from(buffer.subarray(${start}, offset - 1), ${toHex}).join('');` : `${name} = new TextDecoder('${encoding}').decode(buffer.subarray(${start}, offset - 1));`);
        } else if (this.options.greedy) {
          ctx.pushCode(`var ${start} = offset;`);
          ctx.pushCode("while(buffer.length > offset++);");
          ctx.pushCode(isHex ? `${name} = Array.from(buffer.subarray(${start}, offset), ${toHex}).join('');` : `${name} = new TextDecoder('${encoding}').decode(buffer.subarray(${start}, offset));`);
        }
        if (this.options.stripNull) {
          ctx.pushCode(`${name} = ${name}.replace(/\\x00+$/g, '')`);
        }
      }
      generateBuffer(ctx) {
        const varName = ctx.generateVariable(this.varName);
        if (typeof this.options.readUntil === "function") {
          const pred = this.options.readUntil;
          const start = ctx.generateTmpVariable();
          const cur = ctx.generateTmpVariable();
          ctx.pushCode(`var ${start} = offset;`);
          ctx.pushCode(`var ${cur} = 0;`);
          ctx.pushCode(`while (offset < buffer.length) {`);
          ctx.pushCode(`${cur} = dataView.getUint8(offset);`);
          const func = ctx.addImport(pred);
          ctx.pushCode(`if (${func}.call(${ctx.generateVariable()}, ${cur}, buffer.subarray(offset))) break;`);
          ctx.pushCode(`offset += 1;`);
          ctx.pushCode(`}`);
          ctx.pushCode(`${varName} = buffer.subarray(${start}, offset);`);
        } else if (this.options.readUntil === "eof") {
          ctx.pushCode(`${varName} = buffer.subarray(offset);`);
        } else {
          const len = ctx.generateOption(this.options.length);
          ctx.pushCode(`${varName} = buffer.subarray(offset, offset + ${len});`);
          ctx.pushCode(`offset += ${len};`);
        }
        if (this.options.clone) {
          ctx.pushCode(`${varName} = buffer.constructor.from(${varName});`);
        }
      }
      generateArray(ctx) {
        const length = ctx.generateOption(this.options.length);
        const lengthInBytes = ctx.generateOption(this.options.lengthInBytes);
        const type = this.options.type;
        const counter = ctx.generateTmpVariable();
        const lhs = ctx.generateVariable(this.varName);
        const item = ctx.generateTmpVariable();
        const key = this.options.key;
        const isHash = typeof key === "string";
        if (isHash) {
          ctx.pushCode(`${lhs} = {};`);
        } else {
          ctx.pushCode(`${lhs} = [];`);
        }
        if (typeof this.options.readUntil === "function") {
          ctx.pushCode("do {");
        } else if (this.options.readUntil === "eof") {
          ctx.pushCode(`for (var ${counter} = 0; offset < buffer.length; ${counter}++) {`);
        } else if (lengthInBytes !== void 0) {
          ctx.pushCode(`for (var ${counter} = offset + ${lengthInBytes}; offset < ${counter}; ) {`);
        } else {
          ctx.pushCode(`for (var ${counter} = ${length}; ${counter} > 0; ${counter}--) {`);
        }
        if (typeof type === "string") {
          if (!aliasRegistry.get(type)) {
            const typeName = PRIMITIVE_NAMES[type];
            const littleEndian = PRIMITIVE_LITTLE_ENDIANS[type];
            ctx.pushCode(`var ${item} = dataView.get${typeName}(offset, ${littleEndian});`);
            ctx.pushCode(`offset += ${PRIMITIVE_SIZES[type]};`);
          } else {
            const tempVar = ctx.generateTmpVariable();
            ctx.pushCode(`var ${tempVar} = ${FUNCTION_PREFIX + type}(offset, {`);
            if (ctx.useContextVariables) {
              const parentVar = ctx.generateVariable();
              ctx.pushCode(`$parent: ${parentVar},`);
              ctx.pushCode(`$root: ${parentVar}.$root,`);
              if (!this.options.readUntil && lengthInBytes === void 0) {
                ctx.pushCode(`$index: ${length} - ${counter},`);
              }
            }
            ctx.pushCode(`});`);
            ctx.pushCode(`var ${item} = ${tempVar}.result; offset = ${tempVar}.offset;`);
            if (type !== this.alias)
              ctx.addReference(type);
          }
        } else if (type instanceof _Parser) {
          ctx.pushCode(`var ${item} = {};`);
          const parentVar = ctx.generateVariable();
          ctx.pushScope(item);
          if (ctx.useContextVariables) {
            ctx.pushCode(`${item}.$parent = ${parentVar};`);
            ctx.pushCode(`${item}.$root = ${parentVar}.$root;`);
            if (!this.options.readUntil && lengthInBytes === void 0) {
              ctx.pushCode(`${item}.$index = ${length} - ${counter};`);
            }
          }
          type.generate(ctx);
          if (ctx.useContextVariables) {
            ctx.pushCode(`delete ${item}.$parent;`);
            ctx.pushCode(`delete ${item}.$root;`);
            ctx.pushCode(`delete ${item}.$index;`);
          }
          ctx.popScope();
        }
        if (isHash) {
          ctx.pushCode(`${lhs}[${item}.${key}] = ${item};`);
        } else {
          ctx.pushCode(`${lhs}.push(${item});`);
        }
        ctx.pushCode("}");
        if (typeof this.options.readUntil === "function") {
          const pred = this.options.readUntil;
          const func = ctx.addImport(pred);
          ctx.pushCode(`while (!${func}.call(${ctx.generateVariable()}, ${item}, buffer.subarray(offset)));`);
        }
      }
      generateChoiceCase(ctx, varName, type) {
        if (typeof type === "string") {
          const varName2 = ctx.generateVariable(this.varName);
          if (!aliasRegistry.has(type)) {
            const typeName = PRIMITIVE_NAMES[type];
            const littleEndian = PRIMITIVE_LITTLE_ENDIANS[type];
            ctx.pushCode(`${varName2} = dataView.get${typeName}(offset, ${littleEndian});`);
            ctx.pushCode(`offset += ${PRIMITIVE_SIZES[type]}`);
          } else {
            const tempVar = ctx.generateTmpVariable();
            ctx.pushCode(`var ${tempVar} = ${FUNCTION_PREFIX + type}(offset, {`);
            if (ctx.useContextVariables) {
              ctx.pushCode(`$parent: ${varName2}.$parent,`);
              ctx.pushCode(`$root: ${varName2}.$root,`);
            }
            ctx.pushCode(`});`);
            ctx.pushCode(`${varName2} = ${tempVar}.result; offset = ${tempVar}.offset;`);
            if (type !== this.alias)
              ctx.addReference(type);
          }
        } else if (type instanceof _Parser) {
          ctx.pushPath(varName);
          type.generate(ctx);
          ctx.popPath(varName);
        }
      }
      generateChoice(ctx) {
        const tag = ctx.generateOption(this.options.tag);
        const nestVar = ctx.generateVariable(this.varName);
        if (this.varName) {
          ctx.pushCode(`${nestVar} = {};`);
          if (ctx.useContextVariables) {
            const parentVar = ctx.generateVariable();
            ctx.pushCode(`${nestVar}.$parent = ${parentVar};`);
            ctx.pushCode(`${nestVar}.$root = ${parentVar}.$root;`);
          }
        }
        ctx.pushCode(`switch(${tag}) {`);
        for (const tagString in this.options.choices) {
          const tag2 = parseInt(tagString, 10);
          const type = this.options.choices[tag2];
          ctx.pushCode(`case ${tag2}:`);
          this.generateChoiceCase(ctx, this.varName, type);
          ctx.pushCode("break;");
        }
        ctx.pushCode("default:");
        if (this.options.defaultChoice) {
          this.generateChoiceCase(ctx, this.varName, this.options.defaultChoice);
        } else {
          ctx.generateError(`"Met undefined tag value " + ${tag} + " at choice"`);
        }
        ctx.pushCode("}");
        if (this.varName && ctx.useContextVariables) {
          ctx.pushCode(`delete ${nestVar}.$parent;`);
          ctx.pushCode(`delete ${nestVar}.$root;`);
        }
      }
      generateNest(ctx) {
        const nestVar = ctx.generateVariable(this.varName);
        if (this.options.type instanceof _Parser) {
          if (this.varName) {
            ctx.pushCode(`${nestVar} = {};`);
            if (ctx.useContextVariables) {
              const parentVar = ctx.generateVariable();
              ctx.pushCode(`${nestVar}.$parent = ${parentVar};`);
              ctx.pushCode(`${nestVar}.$root = ${parentVar}.$root;`);
            }
          }
          ctx.pushPath(this.varName);
          this.options.type.generate(ctx);
          ctx.popPath(this.varName);
          if (this.varName && ctx.useContextVariables) {
            if (ctx.useContextVariables) {
              ctx.pushCode(`delete ${nestVar}.$parent;`);
              ctx.pushCode(`delete ${nestVar}.$root;`);
            }
          }
        } else if (aliasRegistry.has(this.options.type)) {
          const tempVar = ctx.generateTmpVariable();
          ctx.pushCode(`var ${tempVar} = ${FUNCTION_PREFIX + this.options.type}(offset, {`);
          if (ctx.useContextVariables) {
            const parentVar = ctx.generateVariable();
            ctx.pushCode(`$parent: ${parentVar},`);
            ctx.pushCode(`$root: ${parentVar}.$root,`);
          }
          ctx.pushCode(`});`);
          ctx.pushCode(`${nestVar} = ${tempVar}.result; offset = ${tempVar}.offset;`);
          if (this.options.type !== this.alias) {
            ctx.addReference(this.options.type);
          }
        }
      }
      generateWrapper(ctx) {
        const wrapperVar = ctx.generateVariable(this.varName);
        const wrappedBuf = ctx.generateTmpVariable();
        if (typeof this.options.readUntil === "function") {
          const pred = this.options.readUntil;
          const start = ctx.generateTmpVariable();
          const cur = ctx.generateTmpVariable();
          ctx.pushCode(`var ${start} = offset;`);
          ctx.pushCode(`var ${cur} = 0;`);
          ctx.pushCode(`while (offset < buffer.length) {`);
          ctx.pushCode(`${cur} = dataView.getUint8(offset);`);
          const func2 = ctx.addImport(pred);
          ctx.pushCode(`if (${func2}.call(${ctx.generateVariable()}, ${cur}, buffer.subarray(offset))) break;`);
          ctx.pushCode(`offset += 1;`);
          ctx.pushCode(`}`);
          ctx.pushCode(`${wrappedBuf} = buffer.subarray(${start}, offset);`);
        } else if (this.options.readUntil === "eof") {
          ctx.pushCode(`${wrappedBuf} = buffer.subarray(offset);`);
        } else {
          const len = ctx.generateOption(this.options.length);
          ctx.pushCode(`${wrappedBuf} = buffer.subarray(offset, offset + ${len});`);
          ctx.pushCode(`offset += ${len};`);
        }
        if (this.options.clone) {
          ctx.pushCode(`${wrappedBuf} = buffer.constructor.from(${wrappedBuf});`);
        }
        const tempBuf = ctx.generateTmpVariable();
        const tempOff = ctx.generateTmpVariable();
        const tempView = ctx.generateTmpVariable();
        const func = ctx.addImport(this.options.wrapper);
        ctx.pushCode(`${wrappedBuf} = ${func}.call(this, ${wrappedBuf}).subarray(0);`);
        ctx.pushCode(`var ${tempBuf} = buffer;`);
        ctx.pushCode(`var ${tempOff} = offset;`);
        ctx.pushCode(`var ${tempView} = dataView;`);
        ctx.pushCode(`buffer = ${wrappedBuf};`);
        ctx.pushCode(`offset = 0;`);
        ctx.pushCode(`dataView = new DataView(buffer.buffer, buffer.byteOffset, buffer.length);`);
        if (this.options.type instanceof _Parser) {
          if (this.varName) {
            ctx.pushCode(`${wrapperVar} = {};`);
          }
          ctx.pushPath(this.varName);
          this.options.type.generate(ctx);
          ctx.popPath(this.varName);
        } else if (aliasRegistry.has(this.options.type)) {
          const tempVar = ctx.generateTmpVariable();
          ctx.pushCode(`var ${tempVar} = ${FUNCTION_PREFIX + this.options.type}(0);`);
          ctx.pushCode(`${wrapperVar} = ${tempVar}.result;`);
          if (this.options.type !== this.alias) {
            ctx.addReference(this.options.type);
          }
        }
        ctx.pushCode(`buffer = ${tempBuf};`);
        ctx.pushCode(`dataView = ${tempView};`);
        ctx.pushCode(`offset = ${tempOff};`);
      }
      generateFormatter(ctx, varName, formatter) {
        if (typeof formatter === "function") {
          const func = ctx.addImport(formatter);
          ctx.pushCode(`${varName} = ${func}.call(${ctx.generateVariable()}, ${varName});`);
        }
      }
      generatePointer(ctx) {
        const type = this.options.type;
        const offset = ctx.generateOption(this.options.offset);
        const tempVar = ctx.generateTmpVariable();
        const nestVar = ctx.generateVariable(this.varName);
        ctx.pushCode(`var ${tempVar} = offset;`);
        ctx.pushCode(`offset = ${offset};`);
        if (this.options.type instanceof _Parser) {
          ctx.pushCode(`${nestVar} = {};`);
          if (ctx.useContextVariables) {
            const parentVar = ctx.generateVariable();
            ctx.pushCode(`${nestVar}.$parent = ${parentVar};`);
            ctx.pushCode(`${nestVar}.$root = ${parentVar}.$root;`);
          }
          ctx.pushPath(this.varName);
          this.options.type.generate(ctx);
          ctx.popPath(this.varName);
          if (ctx.useContextVariables) {
            ctx.pushCode(`delete ${nestVar}.$parent;`);
            ctx.pushCode(`delete ${nestVar}.$root;`);
          }
        } else if (aliasRegistry.has(this.options.type)) {
          const tempVar2 = ctx.generateTmpVariable();
          ctx.pushCode(`var ${tempVar2} = ${FUNCTION_PREFIX + this.options.type}(offset, {`);
          if (ctx.useContextVariables) {
            const parentVar = ctx.generateVariable();
            ctx.pushCode(`$parent: ${parentVar},`);
            ctx.pushCode(`$root: ${parentVar}.$root,`);
          }
          ctx.pushCode(`});`);
          ctx.pushCode(`${nestVar} = ${tempVar2}.result; offset = ${tempVar2}.offset;`);
          if (this.options.type !== this.alias) {
            ctx.addReference(this.options.type);
          }
        } else if (Object.keys(PRIMITIVE_SIZES).indexOf(this.options.type) >= 0) {
          const typeName = PRIMITIVE_NAMES[type];
          const littleEndian = PRIMITIVE_LITTLE_ENDIANS[type];
          ctx.pushCode(`${nestVar} = dataView.get${typeName}(offset, ${littleEndian});`);
          ctx.pushCode(`offset += ${PRIMITIVE_SIZES[type]};`);
        }
        ctx.pushCode(`offset = ${tempVar};`);
      }
      generateSaveOffset(ctx) {
        const varName = ctx.generateVariable(this.varName);
        ctx.pushCode(`${varName} = offset`);
      }
    };
    exports.Parser = Parser;
  }
});

// node_modules/gopro-telemetry/code/data/keys.js
var require_keys = __commonJS({
  "node_modules/gopro-telemetry/code/data/keys.js"(exports, module) {
    var Parser = require_binary_parser().Parser;
    var keyAndStructParser = new Parser().endianess("big").string("fourCC", { length: 4, encoding: "ascii" }).string("type", { length: 1, encoding: "ascii" }).uint8("size").uint16("repeat");
    var types = {
      c: { func: "string", opt: { encoding: "ascii", stripNull: true } },
      U: { func: "string", opt: { encoding: "ascii", stripNull: true } },
      F: { func: "string", opt: { length: 4, encoding: "ascii" } },
      b: { size: 1, func: "int8" },
      B: { size: 1, func: "uint8" },
      l: { size: 4, func: "int32" },
      L: { size: 4, func: "uint32" },
      q: { size: 4, func: "uint32" },
      //Never tested
      Q: { size: 8, func: "uint64" },
      //Never tested
      d: { size: 8, func: "doublebe" },
      j: { size: 8, func: "int64" },
      J: { size: 8, func: "uint64", forceNum: true },
      f: { size: 4, func: "floatbe" },
      s: { size: 2, func: "int16" },
      S: { size: 2, func: "uint16" },
      "": { size: 1, func: "bit1" },
      "?": { complex: true },
      "\0": { nested: true }
    };
    var translations = {
      SIUN: "units",
      UNIT: "units",
      STNM: "name",
      RMRK: "comment",
      DVNM: "device name"
    };
    var ignore = ["EMPT", "TSMP", "TICK", "TOCK"];
    var stickyTranslations = {
      TMPC: "temperature [\xB0C]",
      GPSF: "fix",
      GPSP: "precision",
      GPSA: "altitude system",
      STMP: "timestamps [\xB5s]"
    };
    var forcedStruct = {
      FACE: [
        "ID,x,y,w,h",
        // HERO6
        "ID,x,y,w,h,null,null,unknown,null,null,null,null,null,null,null,null,null,null,null,null,null,null,smile",
        // HERO7
        "ID,x,y,w,h,confidence %,smile %",
        // HERO8
        "ver,confidence %,ID,x,y,w,h,smile %, blink %"
        // HERO10
      ]
    };
    var mgjsonMaxArrs = {
      FACE: 2
    };
    function generateStructArr(key, partial) {
      const example = partial.find((arr) => Array.isArray(arr) && arr.length);
      if (!example) return;
      const length = example.length;
      const strings = forcedStruct[key];
      if (!strings) return;
      const str = strings.find((str2) => str2.split(",").length === length);
      if (!str) return null;
      let resultingArr = [];
      str.split(",").forEach((w) => {
        resultingArr.push(w);
      });
      resultingArr = resultingArr.map((v) => v === "null" ? null : v);
      return resultingArr;
    }
    function idKeysTranslation(key) {
      return key.replace(/_?FOUR_?CC/i, "");
    }
    function idValuesTranslation(val, key) {
      const pairs = {
        CLASSIFIER: {
          SNOW: "snow",
          URBA: "urban",
          INDO: "indoor",
          WATR: "water",
          VEGE: "vegetation",
          BEAC: "beach"
        }
      };
      if (pairs[key]) return pairs[key][val] || val;
      return val;
    }
    var names = {
      ACCL: "3-axis accelerometer",
      GYRO: "3-axis gyroscope",
      ISOG: "Image sensor gain",
      SHUT: "Exposure time",
      GPS5: "Latitude, longitude, altitude (WGS 84), 2D ground speed, and 3D speed",
      GPS9: "Lat., Long., Alt., 2D, 3D, days, secs, DOP, fix",
      GPSU: "UTC time and data from GPS",
      GPSF: "GPS Fix",
      GPSP: "GPS Precision - Dilution of Precision (DOP x100)",
      STMP: "Microsecond timestamps",
      FACE: "Face detection boundaring boxes",
      FCNM: "Faces counted per frame",
      ISOE: "Sensor ISO",
      ALLD: "Auto Low Light frame Duration",
      WBAL: "White Balance in Kelvin",
      WRGB: "White Balance RGB gains",
      YAVG: "Luma (Y) Average over the frame",
      HUES: "Predominant hues over the frame",
      UNIF: "Image uniformity",
      SCEN: "Scene classifier in probabilities",
      SROT: "Sensor Read Out Time",
      CORI: "Camera ORIentation",
      IORI: "Image ORIentation",
      GRAV: "GRAvity Vector",
      WNDM: "Wind Processing",
      MWET: "Microphone is WET",
      AALP: "Audio Levels",
      DISP: "Disparity track (360 modes)",
      MAGN: "MAGNnetometer",
      MSKP: "Main video frame SKiP",
      LSKP: "Low res video frame SKiP",
      LOGS: "health logs",
      VERS: "version of the metadata library that created the camera data",
      FMWR: "Firmware version",
      LINF: "Internal IDs",
      CINF: "Internal IDs",
      CASN: "Camera Serial Number",
      MINF: "Camera model",
      MUID: "Media ID",
      CPID: "Capture Identifier",
      CPIN: "Capture number in group",
      CMOD: "Camera Mode",
      MTYP: "Media type",
      HDRV: "HDR Video",
      OREN: "Orientation",
      DZOM: "Digital Zoom enable",
      DZST: "Digital Zoom Setting",
      SMTR: "Spot Meter",
      PRTN: "Protune Enabled",
      PTWB: "Protune White balance",
      PTSH: "Protune Sharpness",
      PTCL: "Protune Color",
      EXPT: "Exposure Type",
      PIMX: "Protune ISO Max",
      PIMN: "Protune ISO Min",
      PTEV: "Protune EV",
      RATE: "Burst Rate, TimeWarp Rate, Timelapse Rate",
      EISE: "Electric Stabilization",
      EISA: "EIS Applied",
      HCTL: "In camera Horizon control",
      AUPT: "Audio Protune",
      APTO: "Audio Protune Option",
      AUDO: "Audio Option",
      AUBT: "Audio BlueTooth",
      PRJT: "Lens Projection",
      CDAT: "Creation Date/Time",
      SCTM: "Schedule Capture Time",
      PRNA: "Preset IDs",
      PRNU: "Preset IDs",
      SCAP: "Schedule Capture",
      CDTM: "Capture Delay Timer (in ms)",
      DUST: "Duration Settings",
      VRES: "Video Resolution",
      VFPS: "Video Framerate ratio",
      HSGT: "Hindsight Settings",
      BITR: "Bitrate",
      MMOD: "Media Mod",
      RAMP: "Speed Ramp Settings",
      TZON: "Time Zone offset in minutes",
      DZMX: "Digital Zoom amount",
      CTRL: "Control Level",
      PWPR: "Power Profile",
      ORDP: "Orientation Data Present",
      CLDP: "Classification Data Present",
      PIMD: "Protune ISO Mode",
      ABSC: "AutoBoost SCore - Used for Autoboost variable prescription modes",
      ZFOV: "Diagon Field Of View in degrees (from corner to corner)",
      VFOV: "Visual FOV style",
      PYCF: "Polynomial power",
      POLY: "Polynomial values",
      ZMPL: "Zoom scale normalization",
      ARUW: "Aspect Ratio of the UnWarped input image",
      ARWA: "Aspect Ratio of the WArped output image",
      MXCF: "Mapping X CoeFficients, Superview/HyperView",
      MAPX: "new_x = ax + bx^3 + cx^5",
      MYCF: "Mapping Y CoeFficients, Superview/HyperView",
      MAPY: "new_y = ay + by^3 + cy^5 + dyx^2 + ey^3x^2 + fyx^4"
    };
    var knownMulti = {
      FACE: true,
      HUES: true,
      SCEN: true
    };
    var computedStreams = ["dateStream"];
    var mp4ValidSamples = ["HLMT"];
    module.exports = {
      keyAndStructParser,
      types,
      translations,
      ignore,
      stickyTranslations,
      generateStructArr,
      mgjsonMaxArrs,
      idKeysTranslation,
      idValuesTranslation,
      names,
      knownMulti,
      computedStreams,
      mp4ValidSamples
    };
  }
});

// node_modules/gopro-telemetry/code/utils/breathe.js
var require_breathe = __commonJS({
  "node_modules/gopro-telemetry/code/utils/breathe.js"(exports, module) {
    var awaiter = typeof setImmediate === "undefined" ? setTimeout : setImmediate;
    module.exports = function() {
      return new Promise((resolve) => awaiter(resolve));
    };
  }
});

// node_modules/gopro-telemetry/code/parseV.js
var require_parseV = __commonJS({
  "node_modules/gopro-telemetry/code/parseV.js"(exports, module) {
    var Parser = require_binary_parser().Parser;
    var { types } = require_keys();
    var breathe = require_breathe();
    var unknown = /* @__PURE__ */ new Set();
    var valueParsers = {};
    function getValueParserForType(type, opts) {
      const key = `${type}-${JSON.stringify(opts)}`;
      if (!valueParsers.hasOwnProperty(key)) {
        valueParsers[key] = new Parser().endianess("big");
        if (!valueParsers[key][types[type].func]) {
          throw new Error(`Unknown type "${type}" (func "${types[type].func}")`);
        }
        valueParsers[key] = valueParsers[key][types[type].func]("value", opts);
      }
      return valueParsers[key];
    }
    function parseV(environment, slice, len, specifics) {
      const { data, options, ks } = environment;
      const { ax = 1, type = ks.type, complexType } = specifics;
      if (ax > 1) {
        let res = [];
        let sliceProgress = 0;
        for (let i = 0; i < ax; i++) {
          let innerType = type;
          if (types[type].complex) innerType = complexType[i];
          if (!types[innerType]) {
            unknown.add(type);
            res.push(null);
          } else {
            const from = slice + sliceProgress;
            const axLen = types[innerType].size || (types[innerType].opt || {}).length || len / ax;
            sliceProgress += axLen;
            res.push(
              parseV(environment, from, axLen, {
                ax: 1,
                type: innerType,
                complexType
              })
            );
          }
        }
        if (options.debug && unknown.size)
          breathe().then(
            () => console.warn("unknown types:", [...unknown].join(","))
          );
        return res;
      } else if (!types[type].complex) {
        let opts = { length: len };
        if (types[type].opt) {
          Object.assign(opts, types[type].opt);
        }
        let valParser = getValueParserForType(type, opts);
        const parsed = valParser.parse(data.subarray(slice));
        if (types[type].forceNum) parsed.value = Number(parsed.value);
        return parsed.value;
      } else throw new Error("Complex type ? with only one axis");
    }
    module.exports = parseV;
  }
});

// node_modules/gopro-telemetry/code/utils/unArrayTypes.js
var require_unArrayTypes = __commonJS({
  "node_modules/gopro-telemetry/code/utils/unArrayTypes.js"(exports, module) {
    function replacer(whole, match0, match1) {
      let replacement = "";
      for (let i = 0; i < match1; i++) replacement += match0;
      return replacement;
    }
    module.exports = function(str) {
      if (/(\w)\[(\d+)\]/g.test(str)) str = str.replace(/(\w)\[(\d+)\]/g, replacer);
      return str;
    };
  }
});

// node_modules/gopro-telemetry/code/parseKLV.js
var require_parseKLV = __commonJS({
  "node_modules/gopro-telemetry/code/parseKLV.js"(exports, module) {
    var {
      keyAndStructParser,
      types,
      generateStructArr,
      mp4ValidSamples
    } = require_keys();
    var parseV = require_parseV();
    var unArrayTypes = require_unArrayTypes();
    var breathe = require_breathe();
    function extendIfNeeded(data, ks, start) {
      let extend = 0;
      if (ks && ks.fourCC === "DEVC") {
        while (data[start + extend] === 0 && data[start + extend + 1] === 0 && data[start + extend + 2] === 0 && data[start + extend + 3] === 0) {
          extend += 4;
        }
      }
      return extend;
    }
    function findLastCC(data, start, end) {
      let ks;
      while (start < end) {
        let length = 0;
        try {
          const tempKs = keyAndStructParser.parse(data.subarray(start));
          if (tempKs.fourCC !== "\0\0\0\0") ks = tempKs;
          length = ks.size * ks.repeat;
        } catch (error) {
          breathe().then(() => console.error(error));
        }
        const reached = start + 8 + (length >= 0 ? length : 0);
        while (start < reached) start += 4;
        start += extendIfNeeded(data, ks, start);
      }
      if (ks) return ks.fourCC;
    }
    async function parseKLV(data, options = {}, { start = 0, end = data.length, parent, unArrayLast = true, gpsTimeSrc }) {
      let result = {};
      let unknown = /* @__PURE__ */ new Set();
      let complexType = [];
      let lastCC = findLastCC(data, start, end);
      if (mp4ValidSamples.includes(lastCC)) unArrayLast = true;
      result.interpretSamples = lastCC;
      if (parent === "STRM" && options.stream && !options.stream.includes(lastCC) && (lastCC !== gpsTimeSrc || options.timeIn === "MP4" && !options.raw || options.streamList || options.deviceList)) {
        return void 0;
      }
      while (start < end) {
        let length = 0;
        let ks;
        try {
          if (start % 2e4 === 0) await breathe();
          try {
            ks = keyAndStructParser.parse(data.subarray(start));
            length = ks.size * ks.repeat;
          } catch (error) {
          }
          const done = !ks || ks.fourCC === "\0\0\0\0" || options.deviceList && ks.fourCC === "STRM" || options.streamList && ks.fourCC === lastCC && parent === "STRM";
          if (!done) {
            let partialResult = [];
            let unArrayLastChild = true;
            if (ks.fourCC === "STRM" && options.mp4header) {
              unArrayLastChild = false;
            }
            if (length < 0) {
              console.warn(
                "Invalid length found. Proceeding but could have errors"
              );
            }
            if (length <= 0) partialResult.push(void 0);
            else if (!types[ks.type]) unknown.add(ks.type);
            else if (types[ks.type].nested) {
              if (data.length >= start + 8 + length) {
                const parsed = await parseKLV(data, options, {
                  start: start + 8,
                  end: start + 8 + length,
                  parent: ks.fourCC,
                  unArrayLast: unArrayLastChild,
                  gpsTimeSrc
                });
                if (parsed != null) partialResult.push(parsed);
              } else partialResult.push(void 0);
            } else if (types[ks.type].func || types[ks.type].complex && complexType) {
              let axes = 1;
              if (types[ks.type].size > 1) axes = ks.size / types[ks.type].size;
              else if (types[ks.type].complex && complexType.length)
                axes = complexType.length;
              if (types[ks.type].func === "string" && ks.size === 1 && ks.repeat > 1) {
                ks.size = length;
                ks.repeat = 1;
              }
              const environment = { data, options, ks };
              const specifics = { ax: axes, complexType };
              if (ks.repeat > 1) {
                for (let i = 0; i < ks.repeat; i++)
                  partialResult.push(
                    parseV(environment, start + 8 + i * ks.size, ks.size, specifics)
                  );
              } else
                partialResult.push(
                  parseV(environment, start + 8, length, specifics)
                );
              if (ks.fourCC === "TYPE")
                complexType = unArrayTypes(partialResult[0]);
              else if (ks.fourCC === "DVID" && parent === "DEVC" && options.device && !options.device.includes(partialResult[0]))
                return void 0;
            } else unknown.add(ks.type);
            if (ks.fourCC === lastCC && generateStructArr(ks.fourCC, partialResult)) {
              let extraDescription = generateStructArr(
                ks.fourCC,
                partialResult
              ).filter((v) => v != null);
              let newValueArr = [];
              partialResult.forEach((p, i) => {
                let descCandidate = [];
                let newP = [];
                generateStructArr(ks.fourCC, partialResult).forEach((e, ii) => {
                  if (Array.isArray(p) && e != null) {
                    descCandidate.push(e);
                    newP.push(p[ii]);
                  } else if (ii === 0 && e != null) descCandidate.push(e);
                });
                if (newP.length) partialResult[i] = newP;
                if (descCandidate.length > extraDescription.length)
                  extraDescription = descCandidate;
              });
              if (newValueArr.length) partialResult[0] = newValueArr;
              if (extraDescription.length) {
                const extraDescString = extraDescription.join(",");
                if (!/\(.+\)$/.test(result.STNM)) {
                  result.STNM = `${result.STNM || ""} (${extraDescString})`;
                } else if (result.STNM.match(/\((.+)\)$/)[1].length < extraDescString.length) {
                  result.STNM.replace(/\(.+\)$/, `(${extraDescString})`);
                }
              }
            }
            if (result.hasOwnProperty(ks.fourCC)) {
              if (parent === "STRM") {
                if (!result.multi) result[ks.fourCC] = [result[ks.fourCC]];
                result[ks.fourCC].push(partialResult);
                result.multi = true;
              } else result[ks.fourCC] = result[ks.fourCC].concat(partialResult);
            } else result[ks.fourCC] = partialResult;
          }
        } catch (err) {
          if (options.tolerant) {
            await breathe();
            console.error(err);
          } else {
            throw err;
          }
        }
        const reached = start + 8 + (length >= 0 ? length : 0);
        while (start < reached) start += 4;
        start += extendIfNeeded(data, ks, start);
      }
      for (const key in result) {
        if ((!unArrayLast || key !== lastCC) && result[key] && result[key].length === 1) {
          result[key] = result[key][0];
        }
      }
      if (options.debug && unknown.size) {
        await breathe();
        console.warn("unknown types:", [...unknown].map((el) => `"${el}"`).join(","));
      }
      return result;
    }
    module.exports = parseKLV;
  }
});

// node_modules/gopro-telemetry/code/groupDevices.js
var require_groupDevices = __commonJS({
  "node_modules/gopro-telemetry/code/groupDevices.js"(exports, module) {
    var { ignore } = require_keys();
    var breathe = require_breathe();
    async function groupDevices(klv) {
      const result = {};
      for (const d of klv.DEVC || []) {
        if (d != null) {
          await breathe();
          ignore.forEach((i) => {
            if (d.hasOwnProperty(i)) delete d[i];
          });
          if (result[d.DVID]) result[d.DVID].DEVC.push(d);
          else result[d.DVID] = { DEVC: [d], interpretSamples: "DEVC" };
        }
      }
      return result;
    }
    module.exports = groupDevices;
  }
});

// node_modules/gopro-telemetry/code/deviceList.js
var require_deviceList = __commonJS({
  "node_modules/gopro-telemetry/code/deviceList.js"(exports, module) {
    function deviceList(klv) {
      const result = {};
      (klv.DEVC || []).filter((d) => d != null).forEach((d) => {
        result[d.DVID] = d.DVNM;
      });
      return result;
    }
    module.exports = deviceList;
  }
});

// node_modules/gopro-telemetry/code/utils/hero7Labelling.js
var require_hero7Labelling = __commonJS({
  "node_modules/gopro-telemetry/code/utils/hero7Labelling.js"(exports, module) {
    var { idKeysTranslation } = require_keys();
    module.exports = function(str, multi) {
      const newStyle = /\[\[([\w,\s]+)\][,\s\.]*\]/;
      if (str && newStyle.test(str)) {
        const inner = str.match(newStyle)[1].split(",").map((s, i) => {
          if (i === 0 && multi) s = idKeysTranslation(s);
          return s.trim();
        }).join(",");
        return str.replace(newStyle, ` (${inner})`);
      }
      return str;
    };
  }
});

// node_modules/gopro-telemetry/code/streamList.js
var require_streamList = __commonJS({
  "node_modules/gopro-telemetry/code/streamList.js"(exports, module) {
    var { translations, names, knownMulti } = require_keys();
    var hero7Labelling = require_hero7Labelling();
    function deviceList(klv) {
      const result = {};
      (klv.DEVC || []).filter((d) => d != null).forEach((d) => {
        if (!result[d.DVID]) result[d.DVID] = {};
        result[d.DVID][translations.DVNM] = d.DVNM;
        result[d.DVID].streams = result[d.DVID].streams || {};
        (d.STRM || []).forEach((s) => {
          if (s.interpretSamples && s.interpretSamples !== "STNM") {
            result[d.DVID].streams[s.interpretSamples] = s.STNM || s.RMRK || names[s.interpretSamples] || s.interpretSamples;
            result[d.DVID].streams[s.interpretSamples] = hero7Labelling(
              result[d.DVID].streams[s.interpretSamples],
              knownMulti[s.interpretSamples]
            );
          }
        });
      });
      return result;
    }
    module.exports = deviceList;
  }
});

// node_modules/gopro-telemetry/code/timeKLV.js
var require_timeKLV = __commonJS({
  "node_modules/gopro-telemetry/code/timeKLV.js"(exports, module) {
    var breathe = require_breathe();
    function GPSUtoDate(GPSU) {
      let regex = /(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\.(\d{3})/;
      let YEAR = 1, MONTH = 2, DAY = 3, HOUR = 4, MIN = 5, SEC = 6, MIL = 7;
      let parts = GPSU.match(regex);
      if (parts) {
        const date = new Date(
          Date.UTC(
            "20" + parts[YEAR],
            parts[MONTH] - 1,
            parts[DAY],
            parts[HOUR],
            parts[MIN],
            parts[SEC],
            parts[MIL]
          )
        );
        return date.getTime();
      }
      return null;
    }
    function GPS9toDate(GPS9) {
      if (GPS9 && GPS9.length > 6) {
        const days = GPS9[5];
        const seconds = GPS9[6];
        const fullSeconds = Math.floor(seconds);
        const milliseconds = (seconds - fullSeconds) * 1e3;
        let date = /* @__PURE__ */ new Date("2000");
        date.setUTCDate(date.getUTCDate() + days);
        date.setUTCSeconds(date.getUTCSeconds() + fullSeconds);
        date.setUTCMilliseconds(date.getUTCMilliseconds() + milliseconds);
        return date.getTime();
      }
      return null;
    }
    async function fillGPSTime(klv, options, timeMeta, gpsTimeSrc) {
      let { gpsDate } = timeMeta;
      let res = [];
      if (options.timeIn === "MP4" || options.mp4header) return res;
      let missingDates = [];
      klv.DEVC.forEach((d, i) => {
        let partialRes;
        let date;
        if (d != null && d.STRM && d.STRM.length) {
          for (const key in d.STRM) {
            if (d.STRM[key][gpsTimeSrc] != null) {
              if (gpsTimeSrc === "GPS5") date = GPSUtoDate(d.STRM[key].GPSU);
              else if (gpsTimeSrc === "GPS9") {
                date = GPS9toDate(d.STRM[key].GPS9[0]);
              }
              delete d.STRM[key].GPSU;
              const doneWithGPSTime = options.stream && !options.stream.includes(gpsTimeSrc) && (!options.dateStream || gpsTimeSrc === "GPS5");
              if (doneWithGPSTime || d.STRM[key].toDelete === "all") {
                delete d.STRM[key];
              } else if (Array.isArray(d.STRM[key].toDelete)) {
                d.STRM[key][gpsTimeSrc] = d.STRM[key][gpsTimeSrc].filter(
                  (_, i2) => d.STRM[key].toDelete[i2]
                );
                delete d.STRM[key].toDelete;
              }
              break;
            }
          }
        }
        if (date != null) {
          if (gpsDate == null) {
            gpsDate = date;
            timeMeta.gpsDate = gpsDate;
          }
          partialRes = { date };
          if (res.length && res[res.length - 1] && res[res.length - 1].date) {
            res[res.length - 1].duration = partialRes.date - res[res.length - 1].date;
          }
        }
        if (partialRes) {
          partialRes.cts = partialRes.date - gpsDate;
          res.push(partialRes);
        } else {
          res.push(null);
          missingDates.push(i);
        }
      });
      let missingDurations = [];
      missingDates.forEach((i) => {
        if (res[i] === null && res[i - 1] && res[i - 1].date) {
          let foundNext = false;
          for (let x = 1; i + x < res.length; x++) {
            if (res[i + x] && res[i + x].date) {
              res[i - 1].duration = (res[i + x].date - res[i - 1].date) / x;
              const index = missingDurations.indexOf(i - 1);
              if (index !== -1) missingDurations.splice(index, 1);
              foundNext = true;
              break;
            }
          }
          if (!foundNext) {
            let lastDuration = 1e3;
            for (let j = i - 2; j >= 0; j--) {
              if (res[j] && res[j].duration) {
                lastDuration = res[j].duration;
                break;
              }
            }
            res[i - 1].duration = lastDuration;
          }
          if (res[i - 1].duration != null) {
            res[i] = { date: res[i - 1].date + res[i - 1].duration };
            res[i].cts = res[i].date - gpsDate;
            missingDurations.push(i);
          }
        }
      });
      let lastMissing = -1;
      while (res[lastMissing + 1] == null && lastMissing < res.length)
        lastMissing++;
      if (lastMissing >= 0 && res.length > lastMissing + 2) {
        const avgDuration = (res.slice(-1)[0].date - res[lastMissing + 1].date) / (res.length - (lastMissing + 1));
        while (lastMissing >= 0) {
          const nextGood = res[lastMissing + 1];
          res[lastMissing] = {
            date: nextGood.date - avgDuration,
            cts: nextGood.cts - avgDuration,
            duration: avgDuration
          };
          lastMissing--;
        }
      }
      if (res[0] && res[0].cts < 0)
        res = res.map((r) => ({ ...r, cts: r.cts - res[0].cts }));
      missingDurations.forEach((i) => {
        if (res[i + 1] && res[i + 1].date)
          res[i].duration = res[i + 1].date - res[i].date;
      });
      if (res.length === 1 && res[0] != null && res[0].duration == null)
        res[0].duration = 1001;
      return res;
    }
    async function fillMP4Time(klv, timing, options, timeMeta) {
      let { offset, mp4Date } = timeMeta;
      if (!offset) offset = 0;
      let res = [];
      if (options.timeIn === "GPS" || options.mp4header) return res;
      if (!timing || !timing.samples || !timing.samples.length) {
        timing = {
          frameDuration: 0.03336666666666667,
          start: /* @__PURE__ */ new Date(),
          samples: [{ cts: 0, duration: 1001 }]
        };
      }
      if (typeof timing.start != "object") timing.start = new Date(timing.start);
      if (!mp4Date) {
        mp4Date = timing.start.getTime();
        timeMeta.mp4Date = mp4Date;
      }
      klv.DEVC.forEach((d, i) => {
        let partialRes = {};
        if (timing.samples[i] != null) {
          partialRes = JSON.parse(JSON.stringify(timing.samples[i]));
          if (offset) partialRes.cts += offset;
        } else {
          partialRes.cts = res[i - 1].cts + (res[i - 1].duration || 0);
          if (i + 1 < klv.DEVC.length) {
            if (res[i - 1].duration) partialRes.duration = res[i - 1].duration;
            else if (i > 1 && res[i - 2].duration) {
              partialRes.duration = res[i - 2].duration;
            }
          }
        }
        partialRes.date = mp4Date + partialRes.cts;
        res.push(partialRes);
        if (d != null && d.STRM && d.STRM.length) {
          for (const key in d.STRM) {
            if (d.STRM[key].GPSU != null) {
              if (options.stream && !options.stream.includes("GPS5") || d.STRM[key].toDelete) {
                delete d.STRM[key];
              } else delete d.STRM[key].GPSU;
              break;
            }
          }
        }
      });
      return res;
    }
    async function timeKLV(klv, { timing, opts = {}, timeMeta = {}, gpsTimeSrc }) {
      let { offset } = timeMeta;
      if (!offset) offset = 0;
      let result;
      try {
        result = JSON.parse(JSON.stringify(klv));
      } catch (error) {
        result = klv;
      }
      const includeTime = opts.timeOut !== "date" || opts.groupTimes;
      const includeDate = opts.timeOut !== "cts";
      try {
        if (result.DEVC && result.DEVC.length) {
          const gpsTimes = await fillGPSTime(result, opts, timeMeta, gpsTimeSrc);
          const mp4Times = await fillMP4Time(result, timing, opts, timeMeta);
          let sDuration = {};
          let dateSDur = {};
          for (let i = 0; i < result.DEVC.length; i++) {
            await breathe();
            const d = result.DEVC[i];
            const { cts, duration } = (() => {
              if (mp4Times.length && mp4Times[i] != null) return mp4Times[i];
              else if (gpsTimes.length && gpsTimes[i] != null) return gpsTimes[i];
              return { cts: null, duration: null };
            })();
            const { date, duration: dateDur } = (() => {
              if (gpsTimes.length && gpsTimes[i] != null) return gpsTimes[i];
              else if (mp4Times.length && mp4Times[i] != null) return mp4Times[i];
              return { date: null, duration: null };
            })();
            const dInitialDate = (() => {
              if (gpsTimes.length && timeMeta.gpsDate) return timeMeta.gpsDate;
              if (mp4Times.length && timeMeta.mp4Date) return timeMeta.mp4Date;
              return 0;
            })();
            const delayDateStream = gpsTimeSrc === "GPS9" && includeDate;
            const dummyStream = {
              STNM: "UTC date/time",
              interpretSamples: "dateStream",
              dateStream: delayDateStream ? [] : ["0"]
            };
            if (d.STRM && opts.dateStream && !delayDateStream) {
              d.STRM.push(dummyStream);
            }
            let skipSTMP = false;
            (d.STRM || []).forEach((s, ii) => {
              if (s.interpretSamples && s[s.interpretSamples] && s[s.interpretSamples].length) {
                const fourCC = s.interpretSamples;
                if (!opts.mp4header) {
                  let currCts;
                  let currDate;
                  if (ii === 0) {
                    if (opts.removeGaps) skipSTMP = true;
                    else if (!mp4Times.length) skipSTMP = true;
                    else if (s.STMP / 1e3 > mp4Times[i].cts + 1e3 * 2) {
                      skipSTMP = true;
                    } else if (s.STMP / 1e3 < mp4Times[i].cts - 1e3 * 2) {
                      skipSTMP = true;
                    }
                  }
                  let microCts = false;
                  let microDuration = false;
                  let microDate = false;
                  let microDateDuration = false;
                  if (s.STMP != null) {
                    if (!skipSTMP) {
                      currCts = s.STMP / 1e3;
                      if (opts.timeIn === "MP4") {
                        currDate = dInitialDate + currCts;
                        microDate = true;
                      }
                      microCts = true;
                      if (result.DEVC[i + 1]) {
                        (result.DEVC[i + 1].STRM || []).forEach((ss) => {
                          if (ss.interpretSamples === fourCC) {
                            if (ss.STMP) {
                              sDuration[fourCC] = (ss.STMP / 1e3 - currCts) / s[fourCC].length;
                              microDuration = true;
                              if (opts.timeIn === "MP4") {
                                dateSDur[fourCC] = sDuration[fourCC];
                                microDateDuration = true;
                              }
                            }
                          }
                        });
                      }
                    }
                    delete s.STMP;
                  }
                  if (!microDuration && duration != null) {
                    sDuration[fourCC] = duration / s[fourCC].length;
                  }
                  if (!microCts) currCts = cts;
                  if (!microDateDuration && dateDur != null) {
                    dateSDur[fourCC] = dateDur / s[fourCC].length;
                  }
                  if (!microDate) currDate = date;
                  let timoDur = 0;
                  if (s.TIMO) {
                    if (s.TIMO * 1e3 > currCts) s.TIMO = currCts / 100;
                    currCts -= s.TIMO * 1e3;
                    if (currCts < 0) currCts = 0;
                    if (d.STRM[ii + 1] && d.STRM[ii + 1].TIMO) {
                      const timoDiff = d.STRM[ii + 1].TIMO - s.TIMO;
                      timoDur = 100 * timoDiff / s[fourCC].length;
                    }
                    currDate -= s.TIMO * 1e3;
                    delete s.TIMO;
                  }
                  s[fourCC] = s[fourCC].map((value) => {
                    if (currCts != null && sDuration[fourCC] != null) {
                      let timedSample = { value };
                      if (includeTime) timedSample.cts = currCts;
                      if (includeDate) {
                        if (gpsTimeSrc === "GPS9" && fourCC === "GPS9") {
                          const GPS9Date = GPS9toDate(value);
                          const date2 = new Date(GPS9Date);
                          timedSample.date = date2;
                          const dateStreamSample = { date: date2, value: GPS9Date };
                          if (includeTime) dateStreamSample.cts = currCts;
                          dummyStream.dateStream.push(dateStreamSample);
                        } else {
                          timedSample.date = new Date(currDate);
                          if (fourCC === "dateStream") {
                            timedSample.value = currDate;
                          }
                        }
                      }
                      currCts += sDuration[fourCC] - timoDur;
                      currDate += dateSDur[fourCC] - timoDur;
                      return timedSample;
                    } else return { value };
                  });
                } else {
                  s[fourCC] = s[fourCC].map((value) => ({
                    value
                  }));
                }
                if (fourCC === gpsTimeSrc && opts.stream && !opts.stream.includes(gpsTimeSrc)) {
                  delete d.STRM[ii];
                }
              }
            });
            if (d.STRM && opts.dateStream && delayDateStream) {
              d.STRM.push(dummyStream);
            }
          }
        } else throw new Error("Invalid data, no DEVC");
      } catch (error) {
        if (opts.tolerant) {
          await breathe();
          console.error(error);
        } else throw error;
      }
      return result;
    }
    module.exports = timeKLV;
  }
});

// node_modules/gopro-telemetry/code/utils/rmrkToNameUnits.js
var require_rmrkToNameUnits = __commonJS({
  "node_modules/gopro-telemetry/code/utils/rmrkToNameUnits.js"(exports, module) {
    module.exports = (rmrk) => {
      const rx = /^struct: (.*)/;
      if (!rx.test(rmrk)) return {};
      const parenthesisRx = / ?\(.*?\)/g;
      let broadString = rmrk.match(rx)[1].replace(/\) (.*)/g, "), $1");
      const name = `(${broadString.replace(parenthesisRx, "").replace(/\bXYZ\b/, "X, Y, Z")})`;
      const commasRx = /(\([^)]*?),([^)]*?\))/g;
      while (broadString.match(commasRx))
        broadString = broadString.replace(commasRx, "$1:REPLACER:$2");
      const broad = broadString.split(",");
      const units = [];
      const unitRx = /\((.+)\)/;
      broad.forEach((v) => {
        if (!unitRx.test(v)) units.push("_");
        else {
          units.push(...v.match(unitRx)[1].split(":REPLACER:"));
        }
      });
      return { name, units };
    };
  }
});

// node_modules/gopro-telemetry/code/interpretKLV.js
var require_interpretKLV = __commonJS({
  "node_modules/gopro-telemetry/code/interpretKLV.js"(exports, module) {
    var { names } = require_keys();
    var rmrkToNameUnits = require_rmrkToNameUnits();
    async function interpretKLV(klv, options) {
      let result;
      try {
        result = JSON.parse(JSON.stringify(klv));
      } catch (e) {
        result = klv;
      }
      if (result != null && result.interpretSamples) {
        const toInterpret = ["SCAL", "altitudeFix", "ORIN", "ORIO", "MTRX", "TYPE"];
        const someMatch = function(a1, a2) {
          for (const elt of a1) if (a2.includes(elt)) return true;
          return false;
        };
        if (someMatch(toInterpret, Object.keys(result))) {
          if (result.hasOwnProperty("ORIN") && result.hasOwnProperty("ORIO")) {
            if (typeof result.ORIO === "string")
              result.ORIO = result.ORIO.split("");
            const labels = `(${result.ORIO.map((o) => o.toLowerCase()).join(",")})`;
            if (result.STNM) result.STNM += ` ${labels}`;
            else result.STNM = labels;
          }
          result[result.interpretSamples] = result[result.interpretSamples].map(
            (s) => {
              if (s == null) return s;
              if (result.hasOwnProperty("SCAL")) {
                if (typeof s === "number") s = s / result.SCAL;
                else if (Array.isArray(s)) {
                  const rescale = (samples) => {
                    if (result.SCAL.length === samples.length) {
                      samples = samples.map(
                        (ss, i) => typeof ss === "number" ? ss / result.SCAL[i] : ss
                      );
                    } else {
                      samples = samples.map(
                        (sss) => typeof sss === "number" ? sss / result.SCAL : sss
                      );
                    }
                    return samples;
                  };
                  if (s.every((ss) => Array.isArray(ss))) s = s.map(rescale);
                  else s = rescale(s);
                }
              }
              if (result.hasOwnProperty("altitudeFix") && (result.GPS5 || result.GPS9) && s && s.length > 2) {
                s[2] = s[2] - result.altitudeFix;
              }
              if (result.hasOwnProperty("ORIN") && result.hasOwnProperty("ORIO")) {
                if (!result.hasOwnProperty("MTRX")) {
                  let newS = [];
                  const len = result.ORIN.length;
                  for (let y = 0; y < len; y++) {
                    for (let x = 0; x < len; x++) {
                      if (result.ORIN[y].toUpperCase() === result.ORIO[x]) {
                        if (result.ORIN[y] === result.ORIO[x]) newS[x] = s[y];
                        else newS[x] = -s[y];
                      }
                    }
                  }
                  s = newS;
                }
              }
              if (result.hasOwnProperty("MTRX")) {
                let newS = [];
                const len = Math.sqrt(result.MTRX.length);
                for (let y = 0; y < len; y++) {
                  for (let x = 0; x < len; x++) {
                    if (result.MTRX[y * len + x] !== 0)
                      newS[x] = s[y] * result.MTRX[y * len + x];
                  }
                }
                s = newS;
              }
              let rmrkName, rmrkUnits;
              if (result.RMRK && /^struct: (.*)/.test(result.RMRK)) {
                const { name, units } = rmrkToNameUnits(result.RMRK);
                rmrkName = name;
                rmrkUnits = units;
              }
              if (!result.hasOwnProperty("STNM")) {
                if (names[result.interpretSamples]) {
                  result.STNM = names[result.interpretSamples];
                } else if (rmrkName) result.STNM = rmrkName;
              }
              if (!result.hasOwnProperty("UNIT") && rmrkUnits)
                result.UNIT = rmrkUnits;
              return s;
            }
          );
        } else if (Array.isArray(result[result.interpretSamples])) {
          result[result.interpretSamples] = await Promise.all(
            result[result.interpretSamples].map((s) => interpretKLV(s, options))
          );
        } else {
          result[result.interpretSamples] = await interpretKLV(
            result[result.interpretSamples],
            options
          );
        }
        toInterpret.forEach((k) => delete result[k]);
      }
      return result;
    }
    module.exports = interpretKLV;
  }
});

// node_modules/gopro-telemetry/code/utils/deduceHeaders.js
var require_deduceHeaders = __commonJS({
  "node_modules/gopro-telemetry/code/utils/deduceHeaders.js"(exports, module) {
    module.exports = function({ units, name }, { inn, out } = {}) {
      let parts;
      if (name) {
        parts = name.match(/.*\((.+?)\).*/);
        if (parts && parts.length) {
          name = name.replace(/\((.+?)\)/, "").trim().replace("  ", " ");
          parts = parts[1].split(",").map((p) => p.trim());
        } else parts = [];
      }
      let unitsHeaders = [];
      if (units) {
        if (Array.isArray(units)) unitsHeaders = units;
        else unitsHeaders[0] = units;
      }
      let headers = [name];
      if (inn == null || out == null) {
        for (let i = 0; i < Math.max(parts.length, unitsHeaders.length); i++) {
          let part = parts[i] || parts[0] ? `(${parts[i] || parts[0]})` : "";
          let unit = unitsHeaders[i] || unitsHeaders[0] ? `[${unitsHeaders[i] || unitsHeaders[0]}]` : "";
          headers[i] = [name, part, unit].filter((e) => e.length).join(" ");
        }
      } else {
        let part = parts.slice(inn, out).length ? `(${parts.slice(inn, out).join(",")})` : "";
        let unit = unitsHeaders.slice(inn, out).length ? `[${unitsHeaders.slice(inn, out).join(",")}]` : "";
        headers = [name, part, unit].filter((e) => e.length).join(" ");
      }
      return headers;
    };
  }
});

// node_modules/gopro-telemetry/code/mergeStream.js
var require_mergeStream = __commonJS({
  "node_modules/gopro-telemetry/code/mergeStream.js"(exports, module) {
    var {
      translations,
      ignore,
      stickyTranslations,
      idKeysTranslation,
      idValuesTranslation,
      mp4ValidSamples
    } = require_keys();
    var deduceHeaders = require_deduceHeaders();
    var hero7Labelling = require_hero7Labelling();
    var breathe = require_breathe();
    function deepEqual(a, b) {
      if (typeof a !== "object" || typeof b !== "object" || a == null || b == null)
        return a === b;
      if (Object.keys(a).length !== Object.keys(b).length) return false;
      for (let i = 0; i < Object.keys(a).length; i++)
        if (!deepEqual(a[Object.keys(a)[i]], b[Object.keys(a)[i]])) return false;
      return true;
    }
    async function mergeStreams(klv, options) {
      const { repeatHeaders, repeatSticky, mp4header } = options;
      let result = { streams: {} };
      let stickies = {};
      for (const d of klv.DEVC || []) {
        if (d != null) {
          stickies[d["device name"]] = stickies[d["device name"]] || {};
          try {
            for (let i = 0; i < d.STRM.length; i++) {
              await breathe();
              const s = d.STRM[i] || {};
              if ((!mp4header || mp4ValidSamples.includes(s.interpretSamples)) && s.interpretSamples && s.interpretSamples !== "STNM") {
                const fourCC = s.interpretSamples;
                stickies[d["device name"]][fourCC] = stickies[d["device name"]][fourCC] || {};
                let samples = s[fourCC];
                delete s[fourCC];
                delete s.interpretSamples;
                const multiple = s.multi;
                delete s.multi;
                if (samples && samples.length) {
                  let sticky = {};
                  let description = { name: fourCC };
                  for (const key in s) {
                    if (translations[key]) description[translations[key]] = s[key];
                    else if (!ignore.includes(key))
                      sticky[stickyTranslations[key] || key] = s[key];
                  }
                  sticky = { ...stickies[d["device name"]][fourCC], ...sticky };
                  if (repeatSticky) {
                    for (let i2 = 0; i2 < samples.length; i2++) {
                      samples[i2] = { ...samples[i2] || {}, ...sticky };
                    }
                  } else if (Object.keys(sticky).length && samples.length) {
                    for (let key in sticky) {
                      if (!deepEqual(
                        sticky[key],
                        stickies[d["device name"]][fourCC][key]
                      )) {
                        samples[0].sticky = samples[0].sticky || {};
                        samples[0].sticky[key] = sticky[key];
                      }
                    }
                  }
                  stickies[d["device name"]][fourCC] = {
                    ...stickies[d["device name"]][fourCC],
                    ...sticky
                  };
                  const workOnHeaders = async function(samples2, desc) {
                    let description2 = JSON.parse(JSON.stringify(desc));
                    let headers = deduceHeaders(description2);
                    for (let i2 = 0; i2 < samples2.length; i2++) {
                      const ss = samples2[i2] || {};
                      if (Array.isArray(ss.value)) {
                        ss.value.forEach(
                          (v, i3) => ss[headers[i3] || `(${i3})`] = v
                        );
                      } else if (headers[0]) ss[headers[0]] = ss.value;
                      if (headers.length) delete ss.value;
                      samples2[i2] = ss;
                    }
                    delete description2.units;
                    delete description2.name;
                    return { samples: samples2, description: description2 };
                  };
                  description.name = hero7Labelling(description.name);
                  const completeSample = async ({ samples: samples2, description: description2 }) => {
                    if (repeatHeaders) {
                      const newResults = await workOnHeaders(samples2, description2);
                      samples2 = newResults.samples;
                      description2 = newResults.description;
                    }
                    if (result.streams[fourCC])
                      result.streams[fourCC].samples.push(...samples2);
                    else result.streams[fourCC] = { samples: samples2, ...description2 };
                  };
                  if (multiple) {
                    let newSamples = {};
                    let idKey = "id";
                    let idPos = 0;
                    let idParts, firstIdParts;
                    if (description.name) {
                      idParts = description.name.match(/(\(.*)\b(ID)\b,?(.*\))$/);
                      if (idParts) {
                        idPos = idParts[0].replace(/\((.*)\)$/, "$1").split(",").indexOf("ID");
                        idKey = "ID";
                      } else {
                        firstIdParts = description.name.match(/\((\w+),?(.*)\)$/i);
                        if (firstIdParts) {
                          idKey = idKeysTranslation(firstIdParts[1]);
                        }
                      }
                    }
                    if (samples[0].value[0] && samples[0].value[0].length === 2) {
                      const headers = [];
                      const newSamples2 = [];
                      for (let i2 = 0; i2 < samples.length; i2++) {
                        const ss = samples[i2] || {};
                        const newSample = { ...ss, value: [] };
                        (ss.value || []).forEach((v, x) => {
                          if (v != null && Array.isArray(v)) {
                            headers[x] = idValuesTranslation(v[0], idKey);
                            newSample.value.push(v[idPos === 1 ? 0 : 1]);
                          }
                        });
                        newSamples2.push(newSample);
                      }
                      if (firstIdParts || idParts) {
                        description.name = description.name.replace(
                          /\((\w+),?(.*)\)$/i,
                          ` | ${idKey}`
                        );
                        if (firstIdParts) {
                          description.units = firstIdParts[2].split(",").map((p) => p.trim());
                        }
                      }
                      description.name += ` (${headers.join(",")})`;
                      await completeSample({ samples: newSamples2, description });
                    } else {
                      if (idParts) {
                        description.name = description.name.replace(
                          idParts[0],
                          idParts[1] + idParts[3]
                        );
                      } else if (firstIdParts) {
                        description.name = description.name.replace(
                          /\((\w+),?(.*)\)$/i,
                          `(${firstIdParts[2]})`
                        );
                      }
                      for (let i2 = 0; i2 < samples.length; i2++) {
                        const ss = samples[i2] || {};
                        (ss.value || []).forEach((v) => {
                          if (v != null && Array.isArray(v)) {
                            let id = v[idPos];
                            if (!newSamples[id]) newSamples[id] = [];
                            let thisSample = {};
                            Object.keys(ss).forEach((k) => {
                              if (k !== "value") thisSample[k] = ss[k];
                            });
                            thisSample.value = [
                              ...v.slice(0, idPos),
                              ...v.slice(idPos + 1)
                            ];
                            if (Array.isArray(thisSample.value) && thisSample.value.length === 1)
                              thisSample.value = thisSample.value[0];
                            newSamples[id].push(thisSample);
                          }
                        });
                      }
                      for (const key in newSamples) {
                        description.subStreamName = `${idKey}:${idValuesTranslation(
                          key,
                          idKey
                        )}`;
                        let desc = description;
                        if (repeatHeaders) {
                          const newResults = await workOnHeaders(
                            newSamples[key],
                            description
                          );
                          newSamples[key] = newResults.samples;
                          desc = newResults.description;
                        }
                        if (result.streams[fourCC + key]) {
                          result.streams[fourCC + key].samples.push(
                            ...newSamples[key]
                          );
                        } else {
                          if (Array.isArray(options.stream) && options.stream.includes(fourCC)) {
                            options.stream.push(fourCC + key);
                          }
                          result.streams[fourCC + key] = {
                            samples: newSamples[key],
                            ...desc
                          };
                        }
                      }
                    }
                  } else await completeSample({ samples, description });
                }
              } else {
                if (s.interpretSamples) delete s.interpretSamples;
                result.streams[`Data ${i}`] = JSON.parse(JSON.stringify(d.STRM));
              }
            }
          } catch (error) {
          }
        }
        delete d.DVID;
        delete d.interpretSamples;
        delete d.STRM;
        for (const key in d) {
          if (translations[key]) result[translations[key]] = d[key];
          else result[key] = d[key];
        }
      }
      return result;
    }
    module.exports = mergeStreams;
  }
});

// node_modules/gopro-telemetry/code/utils/reduceSamples.js
var require_reduceSamples = __commonJS({
  "node_modules/gopro-telemetry/code/utils/reduceSamples.js"(exports, module) {
    function reduceSamples(samples) {
      const keys = new Set(
        samples.reduce((acc, curr) => acc.concat(Object.keys(curr)), [])
      );
      let result = Array.isArray(samples[0]) ? [] : {};
      keys.forEach((k) => {
        const validVals = samples.map((s) => s[k]).filter((v) => v != null);
        if (k === "date") {
          result[k] = new Date(
            validVals.reduce((acc, curr) => acc + new Date(curr).getTime(), 0) / validVals.length
          );
        } else if (!isNaN(validVals[0])) {
          result[k] = validVals.reduce((acc, curr) => acc + curr, 0) / validVals.length;
        } else if (typeof validVals[0] === "object") {
          result[k] = reduceSamples(validVals);
        } else if (validVals[0] === void 0) result[k] = null;
        else result[k] = validVals[0];
      });
      return result;
    }
    module.exports = reduceSamples;
  }
});

// node_modules/gopro-telemetry/code/groupTimes.js
var require_groupTimes = __commonJS({
  "node_modules/gopro-telemetry/code/groupTimes.js"(exports, module) {
    var reduceSamples = require_reduceSamples();
    var breathe = require_breathe();
    function process2Vals(vals, prop, k) {
      if (vals.length < 2) return vals[0] || null;
      else if (typeof vals[0] === "number")
        return vals[0] + (vals[1] - vals[0]) * prop;
      else if (k === "date") {
        return new Date(
          new Date(vals[0]).getTime() + (new Date(vals[1]).getTime() - new Date(vals[0]).getTime()) * prop
        );
      } else if (typeof vals[0] === "object") {
        let result;
        try {
          result = JSON.parse(JSON.stringify(vals[0]));
        } catch (error) {
          result = vals[0];
        }
        for (const key in result)
          result[key] = process2Vals([vals[0][key], vals[1][key]], prop);
        return result;
      } else return vals[0];
    }
    function interpolateSample(samples, i, currentTime) {
      const baseTime = samples[i].cts;
      const difference = samples[i + 1].cts - baseTime;
      const proportion = (currentTime - baseTime) / difference;
      const keys = new Set(
        [samples[i], samples[i + 1]].reduce(
          (acc, curr) => acc.concat(Object.keys(curr)),
          []
        )
      );
      let result = Array.isArray(samples[0]) ? [] : {};
      keys.forEach((k) => {
        const validVals = [samples[i], samples[i + 1]].map((s) => s[k]).filter((v) => v != null);
        result[k] = process2Vals(validVals, proportion, k);
      });
      return result;
    }
    module.exports = async function(klv, { groupTimes, timeOut, disableInterpolation, disableMerging }) {
      const result = {};
      for (const key in klv) {
        const { streams, ...rest } = klv[key];
        result[key] = rest;
        if (streams) {
          result[key].streams = [];
          for (const k in streams) {
            await breathe();
            const { samples, ...rest2 } = streams[k];
            result[key].streams[k] = rest2;
            if (samples) {
              let currentTime = 0;
              let newSamples = [];
              let reachedEnd = false;
              let i = 0;
              while (!reachedEnd) {
                let group = [];
                while (samples[i].cts < currentTime + groupTimes) {
                  group.push(samples[i]);
                  if (i + 1 >= samples.length) {
                    reachedEnd = true;
                    break;
                  } else i++;
                  if (i % 1e3 === 0) await breathe();
                  if (disableMerging) break;
                }
                if (group.length > 1) newSamples.push(reduceSamples(group));
                else if (i > 0 && i < samples.length && !disableInterpolation) {
                  newSamples.push(interpolateSample(samples, i - 1, currentTime));
                } else if (group.length === 1) newSamples.push(group[0]);
                if (timeOut === "date" && newSamples.length)
                  delete newSamples[newSamples.length - 1].cts;
                currentTime += groupTimes;
              }
              result[key].streams[k].samples = newSamples;
            }
          }
        }
      }
      return result;
    };
  }
});

// node_modules/gopro-telemetry/code/smoothSamples.js
var require_smoothSamples = __commonJS({
  "node_modules/gopro-telemetry/code/smoothSamples.js"(exports, module) {
    var reduceSamples = require_reduceSamples();
    var breathe = require_breathe();
    module.exports = async function(klv, { smooth, repeatSticky }) {
      let result;
      try {
        result = JSON.parse(JSON.stringify(klv));
      } catch (error) {
        result = klv;
      }
      for (const key in result) {
        if (result[key].streams) {
          for (const k in result[key].streams) {
            await breathe();
            const samples = result[key].streams[k].samples;
            let newSamples = [];
            if (samples) {
              for (let i = 0; i < samples.length; i++) {
                const ins = Math.max(0, i - smooth);
                const out = Math.min(i + smooth + 1, samples.length);
                let newSample = reduceSamples(samples.slice(ins, out));
                if (samples[i].cts != null) newSample.cts = samples[i].cts;
                if (samples[i].date != null) newSample.date = samples[i].date;
                if (!repeatSticky) {
                  delete newSample.sticky;
                  if (samples[i].sticky) newSample.sticky = samples[i].sticky;
                }
                newSamples.push(newSample);
              }
            }
            result[key].streams[k].samples = newSamples;
          }
        }
      }
      return result;
    };
  }
});

// node_modules/gopro-telemetry/code/decimalPlaces.js
var require_decimalPlaces = __commonJS({
  "node_modules/gopro-telemetry/code/decimalPlaces.js"(exports, module) {
    module.exports = async function(interpreted, { decimalPlaces }) {
      let result = interpreted;
      for (const key in result) {
        if (result[key].streams) {
          for (const k in result[key].streams) {
            const samples = result[key].streams[k].samples;
            let newSamples = [];
            if (samples) {
              for (let i = 0; i < samples.length; i++) {
                let newSample = samples[i];
                for (let j = 0; j < newSample.value.length; j++) {
                  if (!isNaN(newSample.value[j])) {
                    newSample.value[j] = parseFloat(newSample.value[j].toFixed(decimalPlaces));
                  }
                }
                newSamples.push(newSample);
              }
            }
            result[key].streams[k].samples = newSamples;
          }
        }
      }
      return result;
    };
  }
});

// node_modules/gopro-telemetry/code/processGPS.js
var require_processGPS = __commonJS({
  "node_modules/gopro-telemetry/code/processGPS.js"(exports, module) {
    var egm96;
    try {
      egm96 = __require("egm96-universal");
    } catch {
      egm96 = void 0;
    }
    var breathe = require_breathe();
    module.exports = async function(klv, { ellipsoid, GPSPrecision, GPSFix, geoidHeight }, gpsTimeSrc) {
      const evaluateDeletion = (s) => {
        if (s.GPS5) {
          if (GPSFix != null && (s.GPSF == null || s.GPSF < GPSFix)) {
            return "all";
          }
          if (GPSPrecision != null && (s.GPSP == null || s.GPSP > GPSPrecision)) {
            return "all";
          }
          return false;
        } else if (s.GPS9) {
          let accepted = 0;
          let rejected = 0;
          const perSample = [];
          for (const sample of s.GPS9 || []) {
            if (!sample) {
              perSample.push(true);
              continue;
            }
            const fix = sample[8];
            const precision = sample[7];
            if (GPSFix != null) {
              if (fix == null || fix < GPSFix) {
                rejected++;
                perSample.push(true);
                continue;
              }
            }
            if (GPSPrecision != null) {
              if (precision == null || precision > GPSPrecision) {
                rejected++;
                perSample.push(true);
                continue;
              }
            }
            accepted++;
            perSample.push(false);
          }
          if (rejected === s.GPS9.length) return "all";
          if (accepted === s.GPS9.length) return false;
          return perSample.filter((s2) => !!s2).length;
        }
      };
      let result;
      try {
        result = JSON.parse(JSON.stringify(klv));
      } catch (error) {
        result = klv;
      }
      const corrections = {};
      if (!ellipsoid || geoidHeight || GPSFix != null || GPSPrecision != null) {
        for (const d of result.DEVC || []) {
          const length = result.DEVC.length;
          const foundCorrections = {};
          for (let i = ((d || {}).STRM || []).length - 1; i >= 0; i--) {
            await breathe();
            const toDelete = d.STRM[i][gpsTimeSrc] && evaluateDeletion(d.STRM[i]);
            if (toDelete) d.STRM[i].toDelete = toDelete;
            else if ((!foundCorrections.GPS5 || foundCorrections.GPS9) && //If altitude is mean sea level, no need to process it further
            //Otherwise check if all needed info is available
            d.STRM[i].GPSA !== "MSLV" && (!ellipsoid || geoidHeight)) {
              const gpsKey = ["GPS5", "GPS9"].find(
                (k) => d.STRM[i][k] && d.STRM[i][k][0] != null
              );
              if (gpsKey && !foundCorrections[gpsKey]) {
                let fixQuality, precision;
                if (gpsKey === "GPS5" && d.STRM[i].GPSF != null && d.STRM[i].GPSP != null) {
                  fixQuality = d.STRM[i].GPSF / 3;
                  precision = (9999 - d.STRM[i].GPSP) / 9999;
                } else if (gpsKey === "GPS9") {
                  fixQuality = d.STRM[i].GPS9[0][8] / 3;
                  precision = (9999 - 100 * d.STRM[i].GPS9[0][7]) / 9999;
                } else continue;
                corrections[gpsKey] = corrections[gpsKey] || {};
                const centered = (length / 2 - Math.abs(length / 2 - i)) / (length / 2);
                const rating = fixQuality * 10 + precision * 20 + centered;
                if (corrections[gpsKey].rating == null || rating > corrections[gpsKey].rating) {
                  corrections[gpsKey].rating = rating;
                  const scaling = d.STRM[i].SCAL && d.STRM[i].SCAL.length > 1 ? [d.STRM[i].SCAL[0], d.STRM[i].SCAL[1]] : [1, 1];
                  corrections[gpsKey].source = [
                    d.STRM[i][gpsKey][0][0] / scaling[0],
                    d.STRM[i][gpsKey][0][1] / scaling[1]
                  ];
                  foundCorrections[gpsKey] = true;
                }
              }
            }
          }
        }
        let warnEgm;
        for (const k in corrections) {
          if (corrections[k].source) {
            if (egm96) {
              corrections[k].value = egm96.meanSeaLevel(
                corrections[k].source[0],
                corrections[k].source[1]
              );
            } else warnEgm = true;
          }
        }
        if (warnEgm) {
          console.warn(
            "Could not fix altitude. Install optional peer dependency `egm96-universal`"
          );
        }
      }
      (result.DEVC || []).forEach((d) => {
        ((d || {}).STRM || []).forEach((s) => {
          for (const k in corrections) {
            if (corrections[k].value != null) {
              if (s[k]) {
                if (!ellipsoid) s.altitudeFix = corrections[k].value;
                else s.geoidHeight = corrections[k].value;
              }
            }
          }
        });
      });
      return result;
    };
  }
});

// node_modules/gopro-telemetry/code/utils/getSpeed.js
var require_getSpeed = __commonJS({
  "node_modules/gopro-telemetry/code/utils/getSpeed.js"(exports, module) {
    var degToRad = (d) => d * Math.PI / 180;
    var coordsToDist = (lat2, lon2, lat1, lon1) => {
      const earthRadius = 6378137;
      const dLat = degToRad(lat2 - lat1);
      const dLon = degToRad(lon2 - lon1);
      lat1 = degToRad(lat1);
      lat2 = degToRad(lat2);
      const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.sin(dLon / 2) * Math.sin(dLon / 2) * Math.cos(lat1) * Math.cos(lat2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
      return earthRadius * c;
    };
    module.exports = (from, to) => {
      if (!from) return 0;
      const t1 = from.date / 1e3;
      const t2 = to.date / 1e3;
      if (!from.value || !to.value) return null;
      const [lat1, lon1, ele1] = from.value;
      const [lat2, lon2, ele2] = to.value;
      const duration = t2 - t1;
      const distance = coordsToDist(lat2, lon2, lat1, lon1);
      const vertDist = ele2 - ele1;
      const distance3d = Math.sqrt(vertDist ** 2 + distance ** 2);
      return distance3d / duration;
    };
  }
});

// node_modules/gopro-telemetry/code/filterWrongSpeed.js
var require_filterWrongSpeed = __commonJS({
  "node_modules/gopro-telemetry/code/filterWrongSpeed.js"(exports, module) {
    var getSpeed = require_getSpeed();
    module.exports = (samples, maxSpeed) => {
      const tracks = [];
      for (const sample of samples) {
        let destination = { track: null, speed: maxSpeed };
        for (let i = 0; i < tracks.length; i++) {
          const lastSample = tracks[i][tracks[i].length - 1];
          const speed = getSpeed(lastSample, sample);
          if (speed != null && speed < destination.speed) {
            destination = { track: i, speed };
            break;
          }
        }
        if (destination.track == null) {
          if (tracks.length < 15) tracks.push([sample]);
        } else tracks[destination.track].push(sample);
        tracks.sort(
          (a, b) => !a[0].value || a[0].value[0] === 0 && a[0].value[1] === 0 ? Infinity : b.length - a.length
        );
      }
      return tracks[0] || [];
    };
  }
});

// node_modules/gopro-telemetry/code/data/presetsOptions.js
var require_presetsOptions = __commonJS({
  "node_modules/gopro-telemetry/code/data/presetsOptions.js"(exports, module) {
    module.exports = {
      general: {
        mandatory: {
          deviceList: false,
          streamList: false,
          raw: false,
          repeatSticky: false,
          repeatHeaders: false
        },
        preferred: {}
      },
      //geoidheight saves the altitude offset when ellipsoid is enabled, for 3d party interpretation
      gpx: {
        mandatory: {
          dateStream: false,
          stream: "GPS",
          timeOut: null,
          geoidHeight: true
        },
        preferred: { ellipsoid: true }
      },
      virb: {
        mandatory: {
          dateStream: false,
          timeOut: null,
          geoidHeight: true
        },
        preferred: { ellipsoid: true, timeIn: "MP4", stream: "GPS" }
      },
      kml: {
        mandatory: { dateStream: false, stream: "GPS", timeOut: null },
        preferred: {}
      },
      geojson: {
        mandatory: {
          dateStream: false,
          stream: "GPS",
          timeOut: null,
          geoidHeight: true
        },
        preferred: { ellipsoid: true }
      },
      csv: { mandatory: { dateStream: false }, preferred: {} },
      mgjson: {
        mandatory: { dateStream: true, timeOut: null },
        preferred: {
          groupTimes: "frames",
          disableInterpolation: true,
          disableMerging: false
        }
      }
    };
  }
});

// node_modules/gopro-telemetry/code/presets/toGpx.js
var require_toGpx = __commonJS({
  "node_modules/gopro-telemetry/code/presets/toGpx.js"(exports, module) {
    var breathe = require_breathe();
    var fixes = {
      0: "none",
      2: "2d",
      3: "3d"
    };
    async function getGPS5Data(data, comment) {
      let frameRate;
      let inner = "";
      let device = "";
      if (data["frames/second"] != null)
        frameRate = `${Math.round(data["frames/second"])} fps`;
      for (const key in data) {
        if (data[key]["device name"] != null) device = data[key]["device name"];
        if (data[key].streams) {
          for (const stream in data[key].streams) {
            await breathe();
            if ((stream === "GPS5" || stream === "GPS9") && data[key].streams[stream].samples) {
              let units;
              let name;
              if (data[key].streams[stream].name != null) {
                name = data[key].streams[stream].name;
              }
              if (data[key].streams[stream].units != null) {
                units = `[${data[key].streams[stream].units.toString()}]`;
              }
              let sticky = {};
              for (let i = 0; i < data[key].streams[stream].samples.length; i++) {
                const s = data[key].streams[stream].samples[i];
                if (s.value && s.value.length > 1) {
                  if (s.sticky) sticky = { ...sticky, ...s.sticky };
                  let commentParts = [];
                  let cmt = "";
                  let time = "";
                  let ele = "";
                  let fix = "";
                  let hdop = "";
                  let geoidHeight = "";
                  for (const key2 in sticky) {
                    if (key2 === "fix") {
                      if (stream === "GPS5") {
                        fix = `
              <fix>${fixes[sticky[key2]] || "none"}</fix>`;
                      }
                    } else if (key2 === "precision") {
                      if (stream === "GPS5") {
                        hdop = `
              <hdop>${sticky[key2] / 100}</hdop>`;
                      }
                    } else if (key2 === "geoidHeight") {
                      geoidHeight = `
              <geoidheight>${sticky[key2]}</geoidheight>`;
                    } else if (comment) {
                      commentParts.push(`${key2}: ${sticky[key2]}`);
                    }
                  }
                  if (stream === "GPS9") {
                    if (s.value.length > 7) {
                      hdop = `
              <hdop>${s.value[7]}</hdop>`;
                    }
                    if (s.value.length > 8) {
                      fix = `
              <fix>${s.value[8]}</fix>`;
                    }
                  }
                  if (comment) {
                    if (s.value.length > 3) {
                      commentParts.push(`2dSpeed: ${s.value[3]}`);
                    }
                    if (s.value.length > 4) {
                      commentParts.push(`3dSpeed: ${s.value[4]}`);
                    }
                    if (commentParts.length) {
                      cmt = `
              <cmt>${commentParts.join("; ")}</cmt>`;
                    }
                  }
                  if (s.value.length > 1) {
                    ele = `
              <ele>${s.value[2]}</ele>`;
                  }
                  if (s.date != null) {
                    if (typeof s.date != "object") s.date = new Date(s.date);
                    try {
                      time = `
              <time>${s.date.toISOString()}</time>`;
                    } catch (error) {
                      time = `
              <time>${s.date}</time>`;
                    }
                  }
                  const partial = `
          <trkpt lat="${s.value[0]}" lon="${s.value[1]}">
              ${(ele + time + fix + hdop + geoidHeight + cmt).trim()}
          </trkpt>`;
                  if (i === 0 && s.cts > 0) {
                    let firstDate;
                    try {
                      firstDate = new Date(s.date.getTime() - s.cts).toISOString();
                    } catch (e) {
                    }
                    const firstTime = `
              <time>${firstDate}</time>`;
                    const fakeFirst = `
          <trkpt lat="${s.value[0]}" lon="${s.value[1]}">
                ${(ele + firstTime + fix + hdop + geoidHeight + cmt).trim()}
          </trkpt>`;
                    inner += `${fakeFirst}`;
                  }
                  inner += `${partial}`;
                }
              }
              const description = [frameRate, name, units].filter((e) => e != null).join(" - ");
              return { inner, description, device };
            }
          }
        }
      }
      return { inner, description: frameRate || "", device };
    }
    module.exports = async function(data, { name, comment }) {
      const converted = await getGPS5Data(data, comment);
      if (!converted) return void 0;
      let string = `<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="https://github.com/juanirache/gopro-telemetry">
    <trk>
        <name>${name}</name>
        <desc>${converted.description}</desc>
        <src>${converted.device}</src>
        <trkseg>
            ${converted.inner.trim()}
        </trkseg>
  </trk>
</gpx>`;
      return string;
    };
  }
});

// node_modules/gopro-telemetry/code/presets/toVirb.js
var require_toVirb = __commonJS({
  "node_modules/gopro-telemetry/code/presets/toVirb.js"(exports, module) {
    var breathe = require_breathe();
    async function getGPSData(data) {
      let frameRate;
      let inner = "";
      let device = "";
      if (data["frames/second"] != null)
        frameRate = `${Math.round(data["frames/second"])} fps`;
      for (const key in data) {
        if (data[key]["device name"] != null) device = data[key]["device name"];
        if (data[key].streams) {
          for (const stream in data[key].streams) {
            await breathe();
            if ((stream === "GPS5" || stream === "GPS9") && data[key].streams[stream].samples) {
              let name;
              if (data[key].streams[stream].name != null)
                name = data[key].streams[stream].name;
              let units;
              if (data[key].streams[stream].units != null)
                units = `[${data[key].streams[stream].units.toString()}]`;
              let sticky = {};
              for (let i = 0; i < data[key].streams[stream].samples.length; i++) {
                const s = data[key].streams[stream].samples[i];
                if (s.value && s.value.length > 1) {
                  if (s.sticky) sticky = { ...sticky, ...s.sticky };
                  let time = "";
                  let ele = "";
                  let geoidHeight = "";
                  if (sticky.geoidHeight != null)
                    geoidHeight = `
                <geoidheight>${sticky.geoidHeight}</geoidheight>`;
                  if (s.value.length > 1)
                    ele = `
                <ele>${s.value[2]}</ele>`;
                  if (s.date != null) {
                    if (typeof s.date != "object") s.date = new Date(s.date);
                    try {
                      time = `
                <time>${s.date.toISOString().replace(/\.(\d{3})Z$/, "Z")}</time>`;
                    } catch (e) {
                      time = `
                <time>${s.date}</time>`;
                    }
                  }
                  const partial = `
            <trkpt lat="${s.value[0]}" lon="${s.value[1]}">
                ${(ele + time + geoidHeight).trim()}
            </trkpt>`;
                  if (i === 0 && s.cts > 0) {
                    let firstDate;
                    try {
                      firstDate = new Date(s.date.getTime() - s.cts).toISOString().replace(/\.(\d{3})Z$/, "Z");
                    } catch (e) {
                      firstDate = new Date(s.date - s.cts).toISOString().replace(/\.(\d{3})Z$/, "Z");
                    }
                    const firstTime = `
                <time>${firstDate}</time>`;
                    const fakeFirst = `
            <trkpt lat="${s.value[0]}" lon="${s.value[1]}">
                    ${(ele + firstTime + geoidHeight).trim()}
            </trkpt>`;
                    inner += `${fakeFirst}`;
                  }
                  inner += `${partial}`;
                }
              }
              const description = [frameRate, name, units].filter((e) => e != null).join(" - ");
              return { inner, description, device };
            }
          }
        }
      }
      return { inner, description: frameRate || "", device };
    }
    async function getACCLData(data) {
      let frameRate;
      let inner = "";
      let device = "";
      if (data["frames/second"] != null)
        frameRate = `${Math.round(data["frames/second"])} fps`;
      for (const key in data) {
        if (data[key]["device name"] != null) device = data[key]["device name"];
        if (data[key].streams) {
          for (const stream in data[key].streams) {
            await breathe();
            if (stream === "ACCL" && data[key].streams.ACCL.samples) {
              let name;
              if (data[key].streams.ACCL.name != null)
                name = data[key].streams.ACCL.name;
              let units = `[g]`;
              for (let i = 0; i < data[key].streams.ACCL.samples.length; i++) {
                const s = data[key].streams.ACCL.samples[i];
                if (s.value && s.value.length) {
                  let time = "";
                  let acceleration = "";
                  if (s.date != null) {
                    if (typeof s.date != "object") s.date = new Date(s.date);
                    try {
                      time = `
                  <time>${s.date.toISOString()}</time>`;
                    } catch (e) {
                      time = `
                  <time>${s.date}</time>`;
                    }
                  }
                  acceleration = `
                  <extensions>
                    <gpxacc:AccelerationExtension>
                      <gpxacc:accel offset="0" x="${s.value[1] / 9.80665}" y="${s.value[2] / 9.80665}" z="${s.value[0] / 9.80665}"/>
                      <gpxacc:accel offset="0" x="${s.value[1] / 9.80665}" y="${s.value[2] / 9.80665}" z="${s.value[0] / 9.80665}"/>
                    </gpxacc:AccelerationExtension>
                  </extensions>`;
                  const partial = `
              <trkpt lat="0" lon="0">
                  ${(time + acceleration).trim()}
              </trkpt>`;
                  if (i === 0 && s.cts > 0) {
                    let firstDate;
                    try {
                      firstDate = new Date(s.date.getTime() - s.cts).toISOString();
                    } catch (e) {
                      firstDate = new Date(s.date - s.cts).toISOString();
                    }
                    const firstTime = `
                <time>${firstDate}</time>`;
                    const firstAccel = `
                <extensions>
                  <gpxacc:AccelerationExtension>
                    <gpxacc:accel offset="0" x="0" y="0" z="0"/>
                    <gpxacc:accel offset="0" x="0" y="0" z="0"/>
                  </gpxacc:AccelerationExtension>
                </extensions>`;
                    const fakeFirst = `
                <trkpt lat="0" lon="0">
                  ${(firstTime + firstAccel).trim()}
              </trkpt>`;
                    inner += `${fakeFirst}`;
                  }
                  inner += `${partial}`;
                }
              }
              const description = [frameRate, name, units].filter((e) => e != null).join(" - ");
              return { inner, description, device };
            }
          }
        }
      }
      return { inner, description: frameRate || "", device };
    }
    module.exports = async function(data, { name, stream }) {
      let converted;
      if (stream[0] === "GPS5" || stream[0] === "GPS9") {
        converted = await getGPSData(data);
      } else if (stream[0] === "ACCL") converted = await getACCLData(data);
      else return void 0;
      if (!converted) return void 0;
      let string = `<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"
    xmlns:gpxacc="http://www.garmin.com/xmlschemas/AccelerationExtension/v1"
    version="1.1"
    creator="https://github.com/juanirache/gopro-telemetry">
    <trk>
        <name>${name}</name>
        <desc>${converted.description}</desc>
        <src>${converted.device}</src>
        <trkseg>
            ${converted.inner.trim()}
        </trkseg>
  </trk>
</gpx>`;
      return string;
    };
  }
});

// node_modules/gopro-telemetry/code/presets/toKml.js
var require_toKml = __commonJS({
  "node_modules/gopro-telemetry/code/presets/toKml.js"(exports, module) {
    var breathe = require_breathe();
    async function getGPSData(data, comment) {
      let frameRate;
      let device;
      let inner = "";
      if (data["frames/second"] != null)
        frameRate = `${Math.round(data["frames/second"])} fps`;
      for (const key in data) {
        if (data[key]["device name"] != null) device = data[key]["device name"];
        if (data[key].streams) {
          for (const stream in data[key].streams) {
            await breathe();
            if ((stream === "GPS5" || stream === "GPS9") && data[key].streams[stream].samples) {
              let name;
              if (data[key].streams[stream].name != null) {
                name = data[key].streams[stream].name;
              }
              let units;
              if (data[key].streams[stream].units != null) {
                units = data[key].streams[stream].units.toString();
              }
              let sticky = {};
              for (let i = 0; i < data[key].streams[stream].samples.length; i++) {
                const s = data[key].streams[stream].samples[i];
                if (s.value && s.value.length > 1) {
                  if (s.sticky) sticky = { ...sticky, ...s.sticky };
                  let commentParts = [];
                  let cmt = "";
                  let time = "";
                  let altitudeMode = "";
                  if (comment) {
                    for (const key2 in sticky) {
                      if (key2 === "precision") {
                        if (stream === "GPS5") {
                          commentParts.push(`GPS DOP: ${sticky[key2] / 100}`);
                        }
                      } else if (key2 === "fix") {
                        if (stream === "GPS5") {
                          commentParts.push(`GPS Fix: ${sticky[key2]}`);
                        }
                      } else {
                        commentParts.push(`${key2}: ${sticky[key2]}`);
                      }
                    }
                    if (stream === "GPS9") {
                      if (s.value.length > 7) {
                        commentParts.push(`GPS DOP: ${s.value[7]}`);
                      }
                      if (s.value.length > 8) {
                        commentParts.push(`GPS Fix: ${s.value[8]}`);
                      }
                    }
                    if (s.value.length > 3) {
                      commentParts.push(`2D Speed: ${s.value[3]}`);
                    }
                    if (s.value.length > 4) {
                      commentParts.push(`3D Speed: ${s.value[4]}`);
                    }
                    if (commentParts.length) {
                      cmt = `
            <description>${commentParts.join("; ")}</description>`;
                    }
                  }
                  if (s.date != null) {
                    if (typeof s.date != "object") s.date = new Date(s.date);
                    try {
                      time = `
            <TimeStamp>
                <when>${s.date.toISOString()}</when>
            </TimeStamp>`;
                    } catch (e) {
                      time = `
            <TimeStamp>
                <when>${s.date}</when>
            </TimeStamp>`;
                    }
                  }
                  let coords = [s.value[1], s.value[0]];
                  if (s.value.length > 2) {
                    coords.push(s.value[2]);
                    altitudeMode = `
            <altitudeMode>absolute</altitudeMode>`;
                  }
                  const partial = `
        <Placemark>
            ${cmt.trim()}
            <Point>
                ${altitudeMode.trim()}
                <coordinates>${coords.join(",")}</coordinates>
            </Point>
            ${time.trim()}
        </Placemark>`;
                  inner += `${partial}`;
                }
              }
              const description = [device, frameRate, name, units].filter((e) => e != null).join(". ");
              return { inner, description };
            }
          }
        }
      }
      return {
        inner,
        description: [device, frameRate].filter((e) => e != null).join(". ")
      };
    }
    module.exports = async function(data, { name, comment }) {
      const converted = await getGPSData(data, comment);
      let string = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:atom="http://www.w3.org/2005/Atom">
    <Document>
        <name>${name}</name>
        <atom:author>
            <atom:name>gopro-telemetry by Juan Irache</atom:name>
        </atom:author>
        <atom:link href="https://github.com/JuanIrache/gopro-telemetry"/>
        <description>${converted.description}</description>
        ${converted.inner.trim()}
    </Document>
</kml>`;
      return string;
    };
  }
});

// node_modules/gopro-telemetry/code/presets/toGeojson.js
var require_toGeojson = __commonJS({
  "node_modules/gopro-telemetry/code/presets/toGeojson.js"(exports, module) {
    var breathe = require_breathe();
    async function getGPSData(data) {
      let properties = {};
      let coordinates = [];
      for (const key in data) {
        if (data[key]["device name"] != null)
          properties.device = data[key]["device name"];
        if (data[key].streams) {
          for (const stream in data[key].streams) {
            await breathe();
            if ((stream === "GPS5" || stream === "GPS9") && data[key].streams[stream].samples && data[key].streams[stream].samples.length) {
              if (data[key].streams[stream].samples[0].sticky && data[key].streams[stream].samples[0].sticky.geoidHeight) {
                properties.geoidHeight = data[key].streams[stream].samples[0].sticky.geoidHeight;
              }
              properties.AbsoluteUtcMicroSec = [];
              properties.RelativeMicroSec = [];
              for (let i = 0; i < data[key].streams[stream].samples.length; i++) {
                const s = data[key].streams[stream].samples[i];
                if (s.value && s.value.length > 1) {
                  coordinates[i] = [s.value[1], s.value[0]];
                  if (s.value.length > 1) coordinates[i].push(s.value[2]);
                  if (s.date != null) {
                    if (typeof s.date != "object") s.date = new Date(s.date);
                    properties.AbsoluteUtcMicroSec[i] = s.date.getTime();
                  }
                  if (s.cts != null) properties.RelativeMicroSec[i] = s.cts;
                }
              }
              return { coordinates, properties };
            }
          }
        }
      }
      return { coordinates, properties };
    }
    module.exports = async function(data, { name }) {
      const converted = await getGPSData(data);
      let result = {
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: converted.coordinates
        },
        properties: { name, ...converted.properties }
      };
      return result;
    };
  }
});

// node_modules/gopro-telemetry/code/presets/toCsv.js
var require_toCsv = __commonJS({
  "node_modules/gopro-telemetry/code/presets/toCsv.js"(exports, module) {
    var deduceHeaders = require_deduceHeaders();
    var breathe = require_breathe();
    async function createCSV(data) {
      let files = {};
      for (const key in data) {
        let device = key;
        if (data[key]["device name"] != null) device = data[key]["device name"];
        if (data[key].streams) {
          for (const stream in data[key].streams) {
            await breathe();
            if (data[key].streams[stream].samples && data[key].streams[stream].samples.length) {
              let rows = [];
              let name = stream;
              if (data[key].streams[stream].name != null)
                name = data[key].streams[stream].name;
              let units;
              if (data[key].streams[stream].units != null)
                units = data[key].streams[stream].units;
              const headers = deduceHeaders({ name, units });
              let sticky = {};
              for (let i = 0; i < data[key].streams[stream].samples.length; i++) {
                const s = data[key].streams[stream].samples[i];
                if (s.value != null) {
                  if (!Array.isArray(s.value)) s.value = [s.value];
                  if (s.sticky) sticky = { ...sticky, ...s.sticky };
                  if (!rows.length) {
                    let firstRow = [];
                    if (s.cts != null) firstRow.push("cts");
                    if (s.date != null) firstRow.push("date");
                    for (let ii = 0; ii < s.value.length; ii++) {
                      firstRow.push(headers[ii] || ii);
                    }
                    firstRow.push(...Object.keys(sticky));
                    rows.push(
                      firstRow.map((e) => e.toString().replace(/,/g, "|")).join(",")
                    );
                  }
                  let row = [];
                  if (s.cts != null) row.push(s.cts);
                  if (s.date != null) {
                    let processedDate = s.date;
                    if (typeof s.date != "object") processedDate = new Date(s.date);
                    try {
                      row.push(processedDate.toISOString());
                    } catch (e) {
                      row.push(processedDate);
                    }
                    s.date = processedDate;
                  }
                  s.value.forEach((v) => {
                    if (typeof v === "number" || typeof v === "string") row.push(v);
                    else row.push(JSON.stringify(v));
                  });
                  for (const key2 in sticky) row.push(sticky[key2]);
                  rows.push(
                    row.map((e) => e.toString().replace(/,/g, "|")).join(",")
                  );
                }
              }
              files[`${device}-${stream}`] = rows.join("\n");
            }
          }
        }
      }
      return files;
    }
    module.exports = createCSV;
  }
});

// node_modules/gopro-telemetry/code/utils/padStringNumber.js
var require_padStringNumber = __commonJS({
  "node_modules/gopro-telemetry/code/utils/padStringNumber.js"(exports, module) {
    module.exports = function(val, int, dec) {
      let sign = "+";
      if (val[0] === "-") {
        sign = "-";
        val = val.slice(1);
      }
      let integer = val.match(/^(\d*)/);
      if (int) {
        if (!integer || !integer.length) integer = ["0", "0"];
        let padded = integer[1].padStart(int, "0");
        val = val.replace(/^(\d*)/, padded);
      }
      let decimal = val.match(/\.(\d*)$/);
      if (dec) {
        const missingDot = !decimal || !decimal.length;
        if (missingDot) decimal = ["0", "0"];
        let padded = decimal[1].padEnd(dec, "0");
        if (missingDot) val = `${val}.${padded}`;
        else val = val.replace(/(\d*)$/, padded);
      }
      return sign + val;
    };
  }
});

// node_modules/gopro-telemetry/code/utils/bigStr.js
var require_bigStr = __commonJS({
  "node_modules/gopro-telemetry/code/utils/bigStr.js"(exports, module) {
    module.exports = function(num) {
      if (num != null) {
        let numStr = String(num);
        if (Math.abs(num) < 1) {
          let e = parseInt(num.toString().split("e-")[1]);
          if (e) {
            let negative = num < 0;
            if (negative) num *= -1;
            num *= Math.pow(10, e - 1);
            numStr = "0." + new Array(e).join("0") + num.toString().substring(2);
            if (negative) numStr = "-" + numStr;
          }
        } else {
          let e = parseInt(num.toString().split("+")[1]);
          if (e > 20) {
            e -= 20;
            num /= Math.pow(10, e);
            numStr = num.toString() + new Array(e + 1).join("0");
          }
        }
        return numStr;
      }
      return "";
    };
  }
});

// node_modules/gopro-telemetry/code/presets/toMgjson.js
var require_toMgjson = __commonJS({
  "node_modules/gopro-telemetry/code/presets/toMgjson.js"(exports, module) {
    var deduceHeaders = require_deduceHeaders();
    var padStringNumber = require_padStringNumber();
    var bigStr = require_bigStr();
    var { mgjsonMaxArrs } = require_keys();
    var breathe = require_breathe();
    var largestMGJSONNum = 2147483648;
    async function createDataOutlineChildText(matchName, displayName, value) {
      if (typeof value != "string") value = value.toString();
      return {
        objectType: "dataStatic",
        displayName,
        dataType: {
          type: "string",
          paddedStringProperties: {
            maxLen: value.length,
            maxDigitsInStrLength: value.length.toString().length,
            eventMarkerB: false
          }
        },
        matchName,
        value
      };
    }
    async function createDataOutlineChildNumber(matchName, displayName, value) {
      if (isNaN(value)) value = 0;
      else value = +value;
      const digitsInteger = Math.max(bigStr(Math.floor(value)).length, 0);
      const digitsDecimal = Math.max(
        bigStr(value).replace(/^\d*\.?/, "").length,
        0
      );
      return {
        objectType: "dataStatic",
        displayName,
        dataType: {
          type: "number",
          numberStringProperties: {
            pattern: { isSigned: true, digitsInteger, digitsDecimal },
            range: {
              occuring: { min: value, max: value },
              legal: { min: -largestMGJSONNum, max: largestMGJSONNum }
            }
          }
        },
        matchName,
        value
      };
    }
    async function createDynamicDataOutline(matchName, displayName, units, sample, { inn, out } = {}, part, stream) {
      const type = await getDataOutlineType(
        Array.isArray(sample) ? sample.slice(inn, out) : sample
      );
      let result = {
        objectType: "dataDynamic",
        displayName,
        sampleSetID: matchName,
        dataType: { type },
        //We apply (linear) interpolation to numeric values only
        interpolation: type === "paddedString" ? "hold" : "linear",
        hasExpectedFrequecyB: false,
        //Some values will be set afterwards
        sampleCount: null,
        matchName
      };
      if (type === "numberString") {
        if (units && Array.isArray(sample)) {
          const unitsArr = units.split(",");
          result.displayName += ` [${unitsArr[unitsArr.length - 1]}]`;
        } else if (units) result.displayName += ` [${units}]`;
        if (stream && stream.length)
          result.displayName = stream + ": " + result.displayName;
        if (Array.isArray(sample) && part) {
          result.displayName += ` part ${part + 1}`;
        }
        result.dataType.numberStringProperties = {
          pattern: {
            //Will be calculated later
            digitsInteger: 0,
            digitsDecimal: 0,
            //Will use plus and minus signs always. Seems easier
            isSigned: true
          },
          range: {
            //We use the allowed extremes, will compare to actual data
            occuring: { min: largestMGJSONNum, max: -largestMGJSONNum },
            //Legal values could potentially be modified per stream type (for example, latitude within -+85, longitude -+180... but what's the benefit?)
            legal: { min: -largestMGJSONNum, max: largestMGJSONNum }
          }
        };
      } else if (type === "numberStringArray") {
        const partialName = deduceHeaders(
          { name: displayName, units },
          { inn, out }
        );
        if (partialName != result.displayName) result.displayName = partialName;
        else if (part) result.displayName += ` part ${part + 1}`;
        let deducedHeaders = deduceHeaders({ name: displayName, units });
        if (deducedHeaders.length != sample.length) {
          deducedHeaders = sample.map(
            (s, ii) => deducedHeaders[ii] || deducedHeaders[ii - 1] || deducedHeaders[0] || "undefined"
          );
        }
        deducedHeaders = deducedHeaders.slice(inn, out);
        if (stream && stream.length)
          result.displayName = stream + ": " + result.displayName;
        result.dataType.numberArrayProperties = {
          pattern: {
            isSigned: true,
            digitsInteger: 0,
            digitsDecimal: 0
          },
          //Limited to 3 axes, we split the rest to additional streams
          arraySize: sample.slice(inn, out).length,
          //Set tentative headers for each array. much like the repeatHeaders option
          arrayDisplayNames: deducedHeaders,
          arrayRanges: {
            ranges: sample.map((s) => ({
              occuring: { min: largestMGJSONNum, max: -largestMGJSONNum },
              legal: { min: -largestMGJSONNum, max: largestMGJSONNum }
            })).slice(inn, out)
          }
        };
      } else if (type === "paddedString") {
        if (units) result.displayName += `[${units}]`;
        if (stream && stream.length)
          result.displayName = stream + ": " + result.displayName;
        result.dataType.paddedStringProperties = {
          maxLen: 0,
          maxDigitsInStrLength: 0,
          eventMarkerB: false
        };
      }
      return result;
    }
    async function getDataOutlineType(value) {
      if (typeof value === "number" || Array.isArray(value) && value.length && value.length === 1)
        return "numberString";
      else if (Array.isArray(value) && value.length && typeof value[0] === "number")
        return "numberStringArray";
      else return "paddedString";
    }
    async function convertSamples(data) {
      let dataOutline = [];
      let dataDynamicSamples = [];
      for (const key in data) {
        if (data[key].streams) {
          let device = key;
          if (data[key]["device name"] != null) device = data[key]["device name"];
          dataOutline.push(
            await createDataOutlineChildText(`DEVC${key}`, "Device name", device)
          );
          for (const stream in data[key].streams) {
            await breathe();
            if (data[key].streams[stream].samples && data[key].streams[stream].samples.length) {
              let streamName = stream;
              if (data[key].streams[stream].name != null) {
                streamName = data[key].streams[stream].name;
                if (data[key].streams[stream].subStreamName != null) {
                  streamName += " " + data[key].streams[stream].subStreamName;
                }
              }
              let units;
              if (data[key].streams[stream].units != null)
                units = data[key].streams[stream].units;
              const getValidValue = async function(arr, key2) {
                for (const s of arr) if (s[key2] != null) return s[key2];
              };
              let validSample = await getValidValue(
                data[key].streams[stream].samples,
                "value"
              );
              let inout;
              if (Array.isArray(validSample))
                inout = {
                  inn: 0,
                  out: mgjsonMaxArrs[stream.slice(0, 4)] || 3,
                  total: validSample.length
                };
              for (; ; ) {
                const part = inout ? inout.inn / (inout.out - inout.inn) : 0;
                const sampleSetID = `stream${key + "X" + stream + "X" + (part ? part + 1 : "")}`;
                let sampleSet = {
                  sampleSetID,
                  samples: []
                };
                let dataOutlineChild = await createDynamicDataOutline(
                  sampleSetID,
                  streamName,
                  units,
                  validSample,
                  inout,
                  part,
                  stream
                );
                const type = await getDataOutlineType(
                  Array.isArray(validSample) ? validSample.slice(inout.inn, inout.out) : validSample
                );
                const setMaxMinPadStr = function(val, outline) {
                  outline.dataType.paddedStringProperties.maxLen = Math.max(
                    val.toString().length,
                    outline.dataType.paddedStringProperties.maxLen
                  );
                  outline.dataType.paddedStringProperties.maxDigitsInStrLength = Math.max(
                    val.length.toString().length,
                    outline.dataType.paddedStringProperties.maxDigitsInStrLength
                  );
                };
                for (let i = 0; i < data[key].streams[stream].samples.length; i++) {
                  const s = data[key].streams[stream].samples[i];
                  const setMaxMinPadNum = function(val, pattern, range) {
                    range.occuring.min = Math.min(val, range.occuring.min);
                    range.occuring.max = Math.max(val, range.occuring.max);
                    range.legal.min = range.occuring.min;
                    range.legal.max = range.occuring.max;
                    pattern.digitsInteger = Math.max(
                      bigStr(Math.floor(val)).length,
                      pattern.digitsInteger
                    );
                    pattern.digitsDecimal = Math.max(
                      bigStr(val).replace(/^\d*\.?/, "").length,
                      pattern.digitsDecimal
                    );
                  };
                  if (s.value != null) {
                    let sample = { time: new Date(s.cts) };
                    if (type === "numberString") {
                      let singleVal = s.value;
                      if (Array.isArray(s.value)) singleVal = s.value[inout.inn];
                      sample.value = bigStr(singleVal);
                      setMaxMinPadNum(
                        singleVal,
                        dataOutlineChild.dataType.numberStringProperties.pattern,
                        dataOutlineChild.dataType.numberStringProperties.range
                      );
                    } else if (type === "numberStringArray") {
                      sample.value = [];
                      s.value.slice(inout.inn, inout.out).forEach((v, ii) => {
                        sample.value[ii] = bigStr(v);
                        setMaxMinPadNum(
                          v,
                          dataOutlineChild.dataType.numberArrayProperties.pattern,
                          dataOutlineChild.dataType.numberArrayProperties.arrayRanges.ranges[ii]
                        );
                      });
                    } else if (type === "paddedString") {
                      if (stream === "dateStream") {
                        if (s.date != null) {
                          if (typeof s.date != "object") s.date = new Date(s.date);
                          if (!isNaN(s.date)) {
                            s.value = s.date.toISOString();
                          } else {
                            s.value = new Date(s.date).toISOString();
                          }
                        } else s.value = "undefined";
                      }
                      sample.value = {
                        length: s.value.length.toString(),
                        str: s.value
                      };
                      setMaxMinPadStr(s.value, dataOutlineChild);
                    }
                    sampleSet.samples.push(sample);
                  }
                }
                for (let i = 0; i < sampleSet.samples.length; i++) {
                  const s = sampleSet.samples[i];
                  if (type === "numberString") {
                    s.value = padStringNumber(
                      s.value,
                      dataOutlineChild.dataType.numberStringProperties.pattern.digitsInteger,
                      dataOutlineChild.dataType.numberStringProperties.pattern.digitsDecimal
                    );
                  } else if (type === "numberStringArray") {
                    s.value = s.value.map(
                      (v) => padStringNumber(
                        v,
                        dataOutlineChild.dataType.numberArrayProperties.pattern.digitsInteger,
                        dataOutlineChild.dataType.numberArrayProperties.pattern.digitsDecimal
                      )
                    );
                  } else if (type === "paddedString") {
                    s.value.str = s.value.str.padEnd(
                      dataOutlineChild.dataType.paddedStringProperties.maxLen,
                      " "
                    );
                    s.value.length = s.value.length.padStart(
                      dataOutlineChild.dataType.paddedStringProperties.maxDigitsInStrLength,
                      "0"
                    );
                  }
                }
                dataOutlineChild.sampleCount = sampleSet.samples.length;
                dataOutline.push(dataOutlineChild);
                dataDynamicSamples.push(sampleSet);
                if (inout) {
                  if (inout.out >= inout.total) break;
                  const diff = inout.out - inout.inn;
                  inout.inn = inout.out;
                  inout.out += diff;
                } else break;
              }
            }
          }
        }
      }
      return { dataOutline, dataDynamicSamples };
    }
    module.exports = async function(data, { name = "" }) {
      if (data["frames/second"] == null)
        throw new Error("After Effects needs frameRate");
      const converted = await convertSamples(data);
      let result = {
        version: "MGJSON2.0.0",
        creator: "https://github.com/JuanIrache/gopro-telemetry",
        dynamicSamplesPresentB: true,
        dynamicDataInfo: {
          useTimecodeB: false,
          utcInfo: {
            precisionLength: 3,
            isGMT: true
          }
        },
        //Create first data point with filename
        dataOutline: [
          await createDataOutlineChildText("filename", "File name", name),
          ...converted.dataOutline
        ],
        //And paste the converted data
        dataDynamicSamples: converted.dataDynamicSamples
      };
      if (data["frames/second"] != null) {
        result.dataOutline.push(
          await createDataOutlineChildNumber(
            "framerate",
            "Frame rate",
            data["frames/second"]
          )
        );
      }
      if (!result.dataDynamicSamples.length) {
        delete result.dataDynamicSamples;
        delete result.dynamicDataInfo;
        result.dynamicSamplesPresentB = false;
      }
      return result;
    };
  }
});

// node_modules/gopro-telemetry/code/mergeInterpretedSources.js
var require_mergeInterpretedSources = __commonJS({
  "node_modules/gopro-telemetry/code/mergeInterpretedSources.js"(exports, module) {
    var breathe = require_breathe();
    module.exports = async (interpretedArr) => {
      const interpreted = interpretedArr[0];
      for (let i = 1; i < interpretedArr.length; i++) {
        for (const device in interpretedArr[i]) {
          if (!interpreted[device]) {
            interpreted[device] = interpretedArr[i][device];
          } else {
            for (const stream in interpretedArr[i][device].streams) {
              if (interpretedArr[i][device].streams[stream]) {
                await breathe();
                if (!interpreted[device].streams[stream]) {
                  interpreted[device].streams[stream] = interpretedArr[i][device].streams[stream];
                } else if (interpretedArr[i][device].streams[stream].samples) {
                  if (!interpreted[device].streams[stream].samples) {
                    interpreted[device].streams[stream].samples = [];
                  }
                  interpretedArr[i][device].streams[stream].samples.forEach((s) => {
                    interpreted[device].streams[stream].samples.push(s);
                  });
                }
              }
            }
          }
        }
      }
      return interpreted;
    };
  }
});

// node_modules/gopro-telemetry/code/utils/getOffset.js
var require_getOffset = __commonJS({
  "node_modules/gopro-telemetry/code/utils/getOffset.js"(exports, module) {
    module.exports = ({ interpretedArr, i, opts, timing }) => {
      let reachedTime = 0;
      let dev = Object.keys(interpretedArr[i - 1])[0];
      if (dev && interpretedArr[i - 1][dev].streams) {
        const streams = Object.keys(interpretedArr[i - 1][dev].streams);
        for (const stream of streams) {
          const samples = interpretedArr[i - 1][dev].streams[stream].samples;
          if (samples && samples.length) {
            const thisCts = samples[samples.length - 1].cts;
            reachedTime = Math.max(thisCts + 1, reachedTime);
          }
        }
      }
      let prevDuration = timing.slice(0, i).reduce((acc, t) => acc + (1e3 * t.videoDuration || 0), 0);
      prevDuration = Math.max(reachedTime, prevDuration);
      if (opts.removeGaps) return prevDuration;
      else {
        const dateDiff = timing[i].start - timing[0].start;
        return Math.max(dateDiff, prevDuration);
      }
    };
  }
});

// node_modules/gopro-telemetry/code/utils/findFirstTimes.js
var require_findFirstTimes = __commonJS({
  "node_modules/gopro-telemetry/code/utils/findFirstTimes.js"(exports, module) {
    var readUInt8;
    var readUInt16BE;
    var readInt32BE;
    var readInt64BEasFloat;
    if (DataView) {
      readUInt8 = (buffer) => new DataView(buffer.buffer).getUint8(0);
      readUInt16BE = (buffer) => new DataView(buffer.buffer).getUint16(0);
      readInt32BE = (buffer) => new DataView(buffer.buffer).getInt32(0);
      readInt64BEasFloat = (buffer, offset) => Number(new DataView(buffer.buffer).getFloat64(offset));
    } else if (typeof Buffer !== "undefined" && ["readUInt8", "readUInt16BE", "readInt32BE", "readDoubleBE"].every(
      (fn) => Buffer.prototype[fn]
    )) {
      readUInt8 = (buffer) => buffer.readUInt8(0);
      readUInt16BE = (buffer) => buffer.readUInt16BE(0);
      readInt32BE = (buffer) => buffer.readInt32BE(0);
      readInt64BEasFloat = (buffer, offset) => buffer.readDoubleBE(offset);
    } else {
      throw new Error(
        "Please install a compatible `Buffer` or `DataView` polyfill"
      );
    }
    module.exports = (data, forceGPSSrc) => {
      let GPSU;
      let GPS9Time;
      let STMP;
      const checkGPS9 = forceGPSSrc !== "GPS5";
      const checkGPS5 = forceGPSSrc !== "GPS9";
      for (let i = 0; i < 1e5 && i + 4 < (data || []).length; i += 4) {
        if (checkGPS5 && "G" === String.fromCharCode(data[i + 0]) && "P" === String.fromCharCode(data[i + 1]) && "S" === String.fromCharCode(data[i + 2]) && "U" === String.fromCharCode(data[i + 3])) {
          const sizeIdx = i + 5;
          const repeatIdx = i + 6;
          const valIdx = i + 8;
          const size = readUInt8(data.slice(sizeIdx, sizeIdx + 1));
          const repeat = readUInt16BE(data.slice(repeatIdx, repeatIdx + 2));
          const value = data.slice(valIdx, valIdx + size * repeat);
          GPSU = +value.map((i2) => String.fromCharCode(i2)).join("");
        } else if (checkGPS9 && "G" === String.fromCharCode(data[i + 0]) && "P" === String.fromCharCode(data[i + 1]) && "S" === String.fromCharCode(data[i + 2]) && "9" === String.fromCharCode(data[i + 3])) {
          const valIdx = i + 8;
          const daysValue = data.slice(valIdx + 20, valIdx + 24);
          const secondsValue = data.slice(valIdx + 24, valIdx + 28);
          const days = readInt32BE(daysValue);
          const seconds = readInt32BE(secondsValue) / 1e3;
          GPS9Time = seconds + days * 86400;
        } else if ("S" === String.fromCharCode(data[i + 0]) && "T" === String.fromCharCode(data[i + 1]) && "M" === String.fromCharCode(data[i + 2]) && "P" === String.fromCharCode(data[i + 3])) {
          STMP = readInt64BEasFloat(data, i + 8);
        }
        if ((GPS9Time != null || !checkGPS9) && (GPSU != null || !checkGPS5) && STMP != null)
          break;
      }
      return { GPSU, STMP, GPS9Time };
    };
  }
});

// node_modules/gopro-telemetry/index.js
var require_gopro_telemetry = __commonJS({
  "node_modules/gopro-telemetry/index.js"(exports, module) {
    var parseKLV = require_parseKLV();
    var groupDevices = require_groupDevices();
    var deviceList = require_deviceList();
    var streamList = require_streamList();
    var keys = require_keys();
    var timeKLV = require_timeKLV();
    var interpretKLV = require_interpretKLV();
    var mergeStream = require_mergeStream();
    var groupTimes = require_groupTimes();
    var smoothSamples = require_smoothSamples();
    var decimalPlaces = require_decimalPlaces();
    var processGPS = require_processGPS();
    var filterWrongSpeed = require_filterWrongSpeed();
    var presetsOpts = require_presetsOptions();
    var toGpx = require_toGpx();
    var toVirb = require_toVirb();
    var toKml = require_toKml();
    var toGeojson = require_toGeojson();
    var toCsv = require_toCsv();
    var toMgjson = require_toMgjson();
    var mergeInterpretedSources = require_mergeInterpretedSources();
    var breathe = require_breathe();
    var getOffset = require_getOffset();
    var findFirstTimes = require_findFirstTimes();
    async function parseOne({ rawData, parsedData }, opts, gpsTimeSrc) {
      if (parsedData) return parsedData;
      await breathe();
      const parsed = await parseKLV(rawData, opts, { gpsTimeSrc });
      if (!parsed.DEVC) {
        const error = new Error(
          "Invalid GPMF data. Root object must contain DEVC key"
        );
        if (opts.tolerant) {
          await breathe();
          console.error(error);
          return parsed;
        } else throw error;
      }
      return parsed;
    }
    async function interpretOne({ timing, parsed, opts, timeMeta, gpsTimeSrc }) {
      const grouped = await groupDevices(parsed);
      await breathe();
      if (!opts.ellipsoid || opts.geoidHeight || opts.GPSPrecision != null || opts.GPSFix != null) {
        for (const key in grouped)
          grouped[key] = await processGPS(grouped[key], opts, gpsTimeSrc);
      }
      let interpreted = {};
      for (const key in grouped) {
        await breathe();
        interpreted[key] = await interpretKLV(grouped[key], opts);
      }
      let timed = {};
      for (const key in interpreted) {
        await breathe();
        timed[key] = await timeKLV(interpreted[key], {
          timing,
          opts,
          timeMeta,
          gpsTimeSrc
        });
      }
      let merged = {};
      for (const key in timed) {
        await breathe();
        merged[key] = await mergeStream(timed[key], opts);
      }
      if (opts.WrongSpeed != null) {
        for (const key in merged) {
          if (merged[key].streams.GPS5) {
            merged[key].streams.GPS5.samples = filterWrongSpeed(
              merged[key].streams.GPS5.samples,
              opts.WrongSpeed
            );
          }
          if (merged[key].streams.GPS9) {
            merged[key].streams.GPS9.samples = filterWrongSpeed(
              merged[key].streams.GPS9.samples,
              opts.WrongSpeed
            );
          }
        }
      }
      return merged;
    }
    function progress(options, amount) {
      if (options.progress) options.progress(amount);
    }
    async function process(input, opts) {
      await breathe();
      if (presetsOpts[opts.preset]) {
        opts = {
          ...opts,
          ...presetsOpts.general.mandatory,
          ...presetsOpts[opts.preset].mandatory
        };
        for (const key in presetsOpts.general.preferred)
          if (opts[key] == null) opts[key] = presetsOpts.general.preferred[key];
        for (const key in presetsOpts[opts.preset].preferred)
          if (opts[key] == null)
            opts[key] = presetsOpts[opts.preset].preferred[key];
      }
      if (opts.device && !Array.isArray(opts.device)) opts.device = [opts.device];
      if (opts.stream && !Array.isArray(opts.stream)) opts.stream = [opts.stream];
      if (opts.GPSFix == null && opts.GPS5Fix != null) opts.GPSFix = opts.GPS5Fix;
      if (opts.GPSPrecision == null && opts.GPS5Precision != null) {
        opts.GPSPrecision = opts.GPS5Precision;
      }
      const userGPSChoices = ["GPS9", "GPS5"].filter(
        (k) => (opts.stream || []).includes(k)
      );
      const forceGPSSrc = userGPSChoices.length === 1 ? userGPSChoices[0] : null;
      if (!Array.isArray(input)) input = [input];
      const firstTimes = input.map((i) => findFirstTimes(i.rawData, forceGPSSrc));
      let bestGPSTimeSrc;
      if (firstTimes.every((t) => t.GPS9Time)) bestGPSTimeSrc = "GPS9";
      else if (firstTimes.every((t) => t.GPSU)) bestGPSTimeSrc = "GPS5";
      else if (firstTimes.some((t) => t.GPS9Time)) bestGPSTimeSrc = "GPS9";
      else {
        if (opts.timeIn === "GPS") delete opts.timeIn;
        bestGPSTimeSrc = "GPS5";
      }
      if ((opts.stream || []).includes("GPS")) {
        opts.stream = opts.stream.map((s) => s === "GPS" ? bestGPSTimeSrc : s);
      }
      let interpreted;
      let timing;
      progress(opts, 0.01);
      if (input.length === 1) input = input[0];
      if (!Array.isArray(input)) {
        if (input.timing) {
          timing = JSON.parse(JSON.stringify(input.timing));
          timing.start = new Date(timing.start);
        }
        await breathe();
        const gpsTimeSrc = bestGPSTimeSrc;
        const parsed = await parseOne(input, opts, gpsTimeSrc);
        progress(opts, 0.2);
        await breathe();
        if (opts.deviceList) return deviceList(parsed);
        if (opts.streamList) return streamList(parsed);
        if (opts.raw) return parsed;
        await breathe();
        interpreted = await interpretOne({ timing, parsed, opts, gpsTimeSrc });
        progress(opts, 0.4);
      } else {
        if (input.some((i) => !i.timing))
          throw new Error(
            "per-source timing is necessary in order to merge sources"
          );
        if (input.every(
          (i) => i.timing.start.getTime() === input[0].timing.start.getTime()
        )) {
          input.sort((a, b) => {
            const foundA = firstTimes[input.indexOf(a)];
            const foundB = firstTimes[input.indexOf(b)];
            if (foundA.GPS9Time && foundB.GPS9Time) {
              return foundA.GPS9Time - foundB.GPS9Time;
            }
            if (foundA.GPSU && foundB.GPSU) return foundA.GPSU - foundB.GPSU;
            if (foundA.STMP != null && foundB.STMP != null) {
              return foundA.STMP - foundB.STMP;
            }
            return 0;
          });
        }
        timing = input.map((i) => JSON.parse(JSON.stringify(i.timing)));
        timing = timing.map((t) => ({ ...t, start: new Date(t.start) }));
        const getGPSTimeSrc = (i) => firstTimes[i][bestGPSTimeSrc] ? bestGPSTimeSrc : firstTimes[i].GPS9Time ? "GPS9" : "GPS5";
        const parsed = [];
        for (let i = 0; i < input.length; i++) {
          const oneParsed = await parseOne(input[i], opts, getGPSTimeSrc(i));
          parsed.push(oneParsed);
        }
        progress(opts, 0.2);
        await breathe();
        if (opts.deviceList) return parsed.map((p) => deviceList(p));
        if (opts.streamList) return parsed.map((p) => streamList(p));
        if (opts.raw) return parsed;
        const interpretedArr = [];
        let gpsDate, mp4Date;
        for (let i = 0; i < parsed.length; i++) {
          const p = parsed[i];
          await breathe();
          let interpreted2;
          let offset = 0;
          if (i > 0) {
            offset = getOffset({ interpretedArr, i, opts, timing });
          }
          const timeMeta = { gpsDate, mp4Date, offset };
          interpreted2 = await interpretOne({
            timing: timing[i],
            parsed: p,
            opts,
            timeMeta,
            gpsTimeSrc: getGPSTimeSrc(i)
          });
          if (!gpsDate && timeMeta.gpsDate) {
            gpsDate = timeMeta.gpsDate;
          }
          if (!mp4Date && timeMeta.mp4Date) {
            mp4Date = timeMeta.mp4Date;
          }
          interpretedArr.push(interpreted2);
        }
        progress(opts, 0.3);
        await breathe();
        interpreted = await mergeInterpretedSources(interpretedArr);
        progress(opts, 0.4);
        timing = timing[0];
      }
      await breathe();
      if (opts.stream && opts.stream.length) {
        for (const dev in interpreted) {
          for (const stream in interpreted[dev].streams) {
            if (!opts.stream.includes(stream) && !keys.computedStreams.includes(stream)) {
              delete interpreted[dev].streams[stream];
            }
          }
        }
      }
      if (opts.groupTimes === "frames") {
        if (timing && timing.frameDuration) {
          opts.groupTimes = timing.frameDuration * 1e3;
        } else throw new Error("Frame rate is needed for your current options");
      }
      await breathe();
      if (opts.smooth) interpreted = await smoothSamples(interpreted, opts);
      progress(opts, 0.6);
      await breathe();
      if (opts.decimalPlaces) interpreted = await decimalPlaces(interpreted, opts);
      if (opts.groupTimes) interpreted = await groupTimes(interpreted, opts);
      if (timing && timing.frameDuration != null)
        interpreted["frames/second"] = 1 / timing.frameDuration;
      progress(opts, 0.9);
      await breathe();
      if (opts.preset === "gpx") return await toGpx(interpreted, opts);
      if (opts.preset === "virb") return await toVirb(interpreted, opts);
      if (opts.preset === "kml") return await toKml(interpreted, opts);
      if (opts.preset === "geojson") return await toGeojson(interpreted, opts);
      if (opts.preset === "csv") return await toCsv(interpreted);
      if (opts.preset === "mgjson") return await toMgjson(interpreted, opts);
      progress(opts, 1);
      return interpreted;
    }
    async function GoProTelemetry(input, options = {}, callback) {
      const result = await process(input, options);
      if (!callback) return result;
      callback(result);
    }
    module.exports = GoProTelemetry;
    exports = module.exports;
    exports.GoProTelemetry = GoProTelemetry;
    exports.goProTelemetry = GoProTelemetry;
  }
});

// gt-entry.js
var import_gopro_telemetry = __toESM(require_gopro_telemetry());
var export_default = import_gopro_telemetry.default;
export {
  export_default as default
};
