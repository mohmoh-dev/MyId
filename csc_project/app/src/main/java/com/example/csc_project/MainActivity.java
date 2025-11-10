package com.example.csc_project;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override protected void onCreate(Bundle s){
        super.onCreate(s);
        TextView tv = new TextView(this);
        tv.setText("Name: Muhammad Lawal Sani\nReg: U1/22/CSC/1051");
        tv.setTextSize(20);
        setContentView(tv);
    }
}