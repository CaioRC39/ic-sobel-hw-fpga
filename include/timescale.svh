`ifndef TIMESCALE_SVH
`define TIMESCALE_SVH

// Timescale unico do projeto: 1ns de unidade, 1ps de precisao.
// Necessario para simuladores baseados em evento (Icarus/Verilator) terem
// uma nocao de tempo bem definida ao serem dirigidos pelo cocotb, que
// por padrao gera clocks em nanosegundos. Sem isso, o simulador assume
// precisao padrao (tipicamente 1s) e falha ao tentar representar
// periodos de clock menores que 1 segundo.
`timescale 1ns / 1ps

`endif  // TIMESCALE_SVH
