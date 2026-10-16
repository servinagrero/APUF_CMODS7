`timescale 1ns / 1ps

(* keep_hierarchy = "yes" *)
module apuf #(
    parameter STAGES = 64
) (
    input wire clk,
    input wire start,
    input wire [STAGES-1:0] challenge,
    output reg done,
    output reg response
);
    wire [STAGES:0] upper;
    wire [STAGES:0] lower;

    // 1. Clean Launch FF (Eliminates start glitches)
    wire race_launch;
    reg race_reset = 0;
    reg race_trigger = 0;

    (* DONT_TOUCH = "yes", KEEP = "yes" *)
    FDRE #(
        .INIT(1'b0)
    ) launch_ff (
        .D (1'b1),
        .C (clk),
        .CE(race_trigger),
        .R (race_reset),
        .Q (race_launch)
    );

    assign upper[0] = race_launch;
    assign lower[0] = race_launch;

    // 2. The Stages
    genvar i;
    generate
        for (i = 0; i < STAGES; i = i + 1) begin : STAGE
            (* DONT_TOUCH = "yes", KEEP = "yes" *)
            LUT3 #(
                .INIT(8'hCA)
            ) upper_mux (
                .I0(upper[i]),
                .I1(lower[i]),
                .I2(challenge[i]),
                .O (upper[i+1])
            );

            (* DONT_TOUCH = "yes", KEEP = "yes" *)
            LUT3 #(
                .INIT(8'hAC)
            ) lower_mux (
                .I0(upper[i]),
                .I1(lower[i]),
                .I2(challenge[i]),
                .O (lower[i+1])
            );
        end
    endgenerate

    // 3. TRUE NAND SR-Latch Arbiter (INIT=4'h7 is NAND)
    // Resolves terminal asymmetry of FDRE pins
    (* DONT_TOUCH = "yes", KEEP = "yes" *)
    wire puf_out;
    (* DONT_TOUCH = "yes", KEEP = "yes" *)
    wire puf_out_bar;

    (* DONT_TOUCH = "yes", KEEP = "yes" *)
    LUT2 #(
        .INIT(4'h7)
    ) nand_upper (
        .I0(upper[STAGES]),
        .I1(puf_out_bar),
        .O (puf_out)
    );

    (* DONT_TOUCH = "yes", KEEP = "yes" *)
    LUT2 #(
        .INIT(4'h7)
    ) nand_lower (
        .I0(lower[STAGES]),
        .I1(puf_out),
        .O (puf_out_bar)
    );

    // 4. Control Logic
    reg [4:0] start_shift = 0;

    always @(posedge clk) begin
        start_shift <= {start_shift[3:0], start};
        done <= start_shift[4];

        if (start) begin
            race_trigger <= 1'b1;
            race_reset   <= 1'b0;
        end else begin
            race_trigger <= 1'b0;
        end

        if (start_shift[4]) begin
            response   <= puf_out;
            race_reset <= 1'b1;  // Resets the launch_ff for the next race
        end
    end
endmodule
