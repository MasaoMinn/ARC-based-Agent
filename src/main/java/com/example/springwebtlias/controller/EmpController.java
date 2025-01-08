package com.example.springwebtlias.controller;

import com.example.springwebtlias.pojo.Emp;
import com.example.springwebtlias.pojo.PageBean;
import com.example.springwebtlias.pojo.Result;
import com.example.springwebtlias.service.EmpService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;

@Slf4j
@RequestMapping("/emps")
@RestController
public class EmpController {

    @Autowired
    private EmpService empService;
    @GetMapping
    public Result selectByPage(@RequestParam(defaultValue = "1") Integer page, @RequestParam(defaultValue = "10") Integer pageSize, String name, Short gender, @DateTimeFormat(pattern = "yyyy-HH-dd") LocalDateTime begin,@DateTimeFormat(pattern = "yyyy-HH-dd") LocalDateTime end){
        log.info("selectByPage page: {} pageSize: {}", page, pageSize,name,gender,begin,end);
       PageBean pageBean = empService.selectByPage(page,pageSize,name,gender,begin,end);
        return Result.success(pageBean);
    }

    @DeleteMapping("/{ids}")
    public Result delete(@PathVariable List<Integer> ids ){
        log.info("delete: {}", ids);
        empService.delete(ids);
        return Result.success();
    }

    @PostMapping
    public Result save(@RequestBody Emp emp){
        log.info("save: {}", emp);
        empService.save(emp);
        return Result.success();
    }
}
