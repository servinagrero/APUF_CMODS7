`timescale 1ns / 1ps

module top #(
    parameter STAGES = 64,
    parameter CLK_FREQ = 12000000,
    parameter BAUD = 1000000
) (
    input wire clk,
    input wire rst,
    input wire uart_rx_i,
    output wire uart_tx_o,
    output wire [3:0] led_control
);
    // localparam TIMEOUT_CYCLES = 24'd9_600_000;
    localparam TIMEOUT_CYCLES = 24'hFFFFFF;

    initial begin
        if (STAGES < 1) $error("STAGES must be positive.");
        if (STAGES % 8 != 0) $error("STAGES must be a multiple of 8 for byte-framed UART challenges.");
    end

    wire [7:0] rx_data;
    wire rx_valid;
    reg [7:0] tx_data;
    reg tx_start = 0;
    wire tx_busy;

    reg [STAGES-1:0] challenge_reg = 0;

    reg puf_start = 0;
    wire puf_done;
    wire puf_response;

    reg [7:0] byte_count = 0;
    // 24-bit timeout counter (~1.39 seconds at 12 MHz)
    reg [23:0] rx_idle_timer = 0;

    reg response_ready = 0;
    reg [7:0] pending_response = 0;

    uart_rx #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD(BAUD)
    ) rx0 (
        .clk(clk),
        .rst(rst),
        .rx(uart_rx_i),
        .data(rx_data),
        .valid(rx_valid)
    );

    uart_tx #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD(BAUD)
    ) tx0 (
        .clk(clk),
        .rst(rst),
        .data(tx_data),
        .start(tx_start),
        .tx(uart_tx_o),
        .busy(tx_busy)
    );

    apuf #(
        .STAGES(STAGES)
    ) puf0 (
        .clk(clk),
        .start(puf_start),
        .challenge(challenge_reg),
        .done(puf_done),
        .response(puf_response)
    );

    assign led_control[0] = puf_response;
    assign led_control[1] = tx_busy;  // Disabled PDL indicator
    assign led_control[2] = rx_valid;
    assign led_control[3] = puf_done;

    always @(posedge clk) begin
        if (rst) begin
            byte_count <= 0;
            puf_start <= 0;
            tx_start <= 0;
            response_ready <= 0;
            rx_idle_timer <= 0;
        end else begin
            tx_start  <= 0;
            puf_start <= 0;

            // Timer Logic (Error Recovery Only)
            if (rx_valid) begin
                rx_idle_timer <= 0;
            end else if (byte_count > 0) begin
                rx_idle_timer <= rx_idle_timer + 1;
                if (rx_idle_timer >= TIMEOUT_CYCLES) begin
                    byte_count <= 0;
                    rx_idle_timer <= 0;
                end
            end

            // Receive Logic (Streamlined directly into challenge_reg)
            if (rx_valid) begin
                // challenge_reg <= {challenge_reg[STAGES-9:0], rx_data};
                // INDEXED ASSIGNMENT: Maps challenge[0] strictly to Stage 0
                challenge_reg[byte_count*8+:8] <= rx_data;

                if (byte_count == (STAGES / 8) - 1) begin
                    byte_count <= 0;
                    puf_start  <= 1;
                end else begin
                    byte_count <= byte_count + 1;
                end
            end

            // Transmit Logic
            if (puf_done) begin
                pending_response <= {7'b0, puf_response};
                response_ready   <= 1;
            end

            if (response_ready && !tx_busy) begin
                tx_data <= pending_response;
                tx_start <= 1;
                response_ready <= 0;
            end
        end
    end
endmodule
